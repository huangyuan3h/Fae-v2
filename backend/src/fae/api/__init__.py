"""FastAPI entry point.

Checkpoint 1: /health, /ready.
Checkpoint 2: /api/test-connection, /api/chat (text-only LLM).
Checkpoint 3: /ws/chat (streaming WebSocket chat).
Phase 1.2/1.3: /api/sessions, /api/pipeline/text (text pipeline smoke).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pathlib import Path

from fae.agent.prepare import prepare_chat_request
from fae.agent.skills_loader import default_skills_dir
from fae.agent.skills_runtime import SkillRuntime
from fae.api.deps import get_llm_client
from fae.api.memory import router as memory_router
from fae.api.notifications import router as notifications_router
from fae.api.pipeline import router as pipeline_router
from fae.api.schedules import router as schedules_router
from fae.api.schedules import status_router as scheduler_status_router
from fae.api.skills import router as skills_router
from fae.api.tts import router as tts_router
from fae.api.voice import router as voice_router
from fae.api.ws import router as ws_router
from fae.channels.bridge import handle_inbound_text, resolve_server_llm_config
from fae.channels.telegram import TelegramClient, telegram_poll_loop, telegram_ready
from fae.config import REPO_ROOT, Settings, get_settings
from fae.llm import (
    ChatRequest,
    ChatResponse,
    LLMClient,
    LLMConfig,
    LLMError,
    OpenAICompatibleProvider,
)
from fae.memory.consolidation import MemoryConsolidator, SleeptimeScheduler
from fae.memory.factory import MemoryStack, create_memory_stack
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.scheduler import ActivityTracker, ConnectionHub, ProactiveLoop, ScheduleStore
from fae.scheduler.delivery import NotificationDelivery
from fae.scheduler.jobs import builtin_job_specs
from fae.sessions import SessionStore
from fae.voice_runtime import VoiceRuntime


def _schedules_db_path(settings: Settings) -> Path:
    db_path = Path(settings.schedules_db_path)
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    return db_path


def _seed_builtin_jobs(store: ScheduleStore) -> None:
    specs = builtin_job_specs()
    store.ensure_builtin_jobs(
        [(s.id, "cron", s.cron, s.description, s.meta) for s in specs]
    )


def _proactive_llm_config(settings: Settings) -> LLMConfig:
    """Server-side model for proactive loop (never reads browser localStorage)."""
    cfg = resolve_server_llm_config(settings)
    if cfg is not None:
        return cfg
    # Placeholder so ProactiveLoop can still construct; generation fails soft.
    return LLMConfig(
        api_key="unused",
        base_url=(settings.proactive_llm_base_url or "").strip()
        or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model=(settings.proactive_llm_model or "").strip() or "qwen3-max",
    )


logger = logging.getLogger("fae")


def _build_sleeptime(
    settings: Settings, stack: MemoryStack
) -> SleeptimeScheduler | None:
    if (
        not settings.sleeptime_enabled
        or stack.client is None
        or stack.recall is None
    ):
        return None
    consolidator = MemoryConsolidator(
        stack.client,
        stack.recall,
        archival=stack.archival,
        compactor=stack.compactor,
        current_char_limit=settings.core_current_char_limit,
        max_runtime_s=settings.sleeptime_max_runtime_s,
    )
    return SleeptimeScheduler(
        consolidator,
        idle_seconds=float(settings.sleeptime_idle_seconds),
        poll_seconds=float(settings.sleeptime_poll_seconds),
        min_interval_s=float(settings.sleeptime_min_interval_s),
        daily_hour=settings.sleeptime_daily_hour,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks.

    - Wire Letta / embedded memory into app.state.memory.
    - Start sleeptime scheduler when memory is enabled.
    - Cancel in-flight Daily bots on shutdown.
    """
    settings: Settings = app.state.settings
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)

    if getattr(app.state, "sleeptime", None) is None:
        app.state.sleeptime = None

    hub: ConnectionHub = getattr(app.state, "ws_hub", None) or ConnectionHub()
    app.state.ws_hub = hub

    # Schedule store always available for REST even when loop is disabled.
    # Recreate if previous lifespan closed the connection.
    store = getattr(app.state, "schedule_store", None)
    if not isinstance(store, ScheduleStore):
        store = ScheduleStore(_schedules_db_path(settings))
        app.state.schedule_store = store
    _seed_builtin_jobs(store)

    activity = getattr(app.state, "activity", None)
    if not isinstance(activity, ActivityTracker):
        activity = ActivityTracker(store=store)
    else:
        activity.bind_store(store)
    app.state.activity = activity
    delivery = NotificationDelivery(
        store,
        hub,
        vapid_public_key=settings.vapid_public_key,
        vapid_private_key=settings.vapid_private_key,
        vapid_subject=settings.vapid_subject,
        notifications_enabled=settings.notifications_enabled,
    )
    app.state.delivery = delivery

    # Allow tests to pre-set app.state.memory before lifespan runs.
    if getattr(app.state, "memory", None) is None:
        stack: MemoryStack | None = None
        try:
            stack = await create_memory_stack(settings)
            app.state.memory_stack = stack
            app.state.recall_store = stack.recall
            app.state.archival = stack.archival
            app.state.episodic = stack.episodic
            scheduler = _build_sleeptime(settings, stack)
            app.state.sleeptime = scheduler

            def _on_persist(session_id: str) -> None:
                activity.touch(session_id)
                if scheduler is not None:
                    scheduler.touch(session_id)

            if stack.client is not None:
                app.state.memory = LettaMemoryService(
                    stack.client,
                    archival=stack.archival,
                    compactor=stack.compactor,
                    episodic=stack.episodic,
                    on_persist=_on_persist,
                )
                app.state.memory_client = stack.client
            else:
                app.state.memory = None
                app.state.memory_client = None
            if scheduler is not None:
                await scheduler.start()
        except Exception:  # noqa: BLE001
            logger.exception("Memory bootstrap failed — continuing without memory")
            if stack is not None:
                try:
                    await stack.close()
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to close partial memory stack")
            app.state.memory = None
            app.state.memory_client = None
            app.state.memory_stack = MemoryStack()
            app.state.recall_store = None
            app.state.archival = None
            app.state.episodic = None
            app.state.sleeptime = None

    # Phase 4 proactive loop — recreate after prior shutdown cleared the handle.
    if settings.scheduler_enabled:
        existing = getattr(app.state, "proactive", None)
        if isinstance(existing, ProactiveLoop) and existing._started:
            pass
        else:
            llm_cfg = _proactive_llm_config(settings)
            loop = ProactiveLoop(
                store=store,
                activity=activity,
                delivery=delivery,
                skills=getattr(app.state, "skills", None),
                llm=getattr(app.state, "llm_client", None),
                memory=getattr(app.state, "memory", None),
                episodic=getattr(app.state, "episodic", None),
                recall=getattr(app.state, "recall_store", None),
                sleeptime=getattr(app.state, "sleeptime", None),
                heartbeat_seconds=settings.heartbeat_seconds,
                outreach_idle_hours=settings.outreach_idle_hours,
                outreach_cooldown_hours=settings.outreach_cooldown_hours,
                outreach_max_per_day=settings.outreach_max_per_day,
                default_llm_config=llm_cfg,
                default_city=getattr(settings, "weather_default_city", "") or "",
                default_timezone=getattr(settings, "weather_default_timezone", "")
                or "",
            )
            app.state.proactive = loop
            await loop.start()
    else:
        app.state.proactive = None

    # Phase 5.1 Telegram long-polling channel (optional).
    tg_task: asyncio.Task[None] | None = None
    tg_client: TelegramClient | None = None
    tg_stop = asyncio.Event()
    app.state.telegram_task = None
    app.state.telegram_client = None
    if telegram_ready(settings):
        token = settings.telegram_bot_token.strip()
        chat_id = settings.telegram_chat_id.strip()
        tg_client = TelegramClient(token)
        app.state.telegram_client = tg_client

        async def _tg_send(text: str) -> bool:
            return await tg_client.send_message(chat_id, text)

        delivery.set_telegram_sender(_tg_send)

        async def _on_tg_text(text: str) -> str:
            skills_rt = getattr(app.state, "skills", None)
            proactive = getattr(app.state, "proactive", None)

            def _resync() -> None:
                if isinstance(proactive, ProactiveLoop):
                    proactive.resync()

            return await handle_inbound_text(
                text,
                settings=settings,
                llm=app.state.llm_client,
                memory=getattr(app.state, "memory", None),
                skills=skills_rt if isinstance(skills_rt, SkillRuntime) else None,
                schedule_store=getattr(app.state, "schedule_store", None),
                activity=getattr(app.state, "activity", None),
                session_id="default",
                on_schedule_mutated=_resync,
            )

        tg_task = asyncio.create_task(
            telegram_poll_loop(
                tg_client,
                allowed_chat_id=chat_id,
                on_text=_on_tg_text,
                stop_event=tg_stop,
            ),
            name="fae-telegram-poll",
        )
        app.state.telegram_task = tg_task
        logger.info("Telegram channel enabled (chat_id=%s)", chat_id)
    else:
        delivery.set_telegram_sender(None)

    yield

    tg_stop.set()
    if tg_task is not None:
        tg_task.cancel()
        try:
            await tg_task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("telegram task shutdown error", exc_info=True)
    app.state.telegram_task = None
    if tg_client is not None:
        try:
            await tg_client.close()
        except Exception:  # noqa: BLE001
            logger.debug("telegram client close failed", exc_info=True)
    app.state.telegram_client = None

    runtime = getattr(app.state, "voice_runtime", None)
    if runtime is not None:
        await runtime.shutdown()
    proactive = getattr(app.state, "proactive", None)
    if isinstance(proactive, ProactiveLoop):
        await proactive.stop()
    app.state.proactive = None
    scheduler = getattr(app.state, "sleeptime", None)
    if isinstance(scheduler, SleeptimeScheduler):
        await scheduler.stop()
    stack = getattr(app.state, "memory_stack", None)
    if isinstance(stack, MemoryStack):
        await stack.close()
    else:
        mem_client = getattr(app.state, "memory_client", None)
        if mem_client is not None:
            try:
                await mem_client.close()
            except Exception:  # noqa: BLE001
                logger.exception("memory_client.close failed")
    schedule_store = getattr(app.state, "schedule_store", None)
    if isinstance(schedule_store, ScheduleStore):
        schedule_store.close()
    app.state.schedule_store = None
    app.state.delivery = None
    logger.info("Shutting down %s", settings.app_name)


# ── HTTP error mapping for LLMError ───────────────────────────────────
_HTTP_FOR_LLM_CODE: dict[str, int] = {
    "auth": 401,
    "forbidden": 403,
    "not_found": 404,
    "bad_request": 400,
    "rate_limited": 429,
    "timeout": 504,
    "connection": 502,
    "length": 502,
    "empty_response": 502,
    "unknown": 500,
}


def _llm_error_to_http(err: LLMError) -> HTTPException:
    status = _HTTP_FOR_LLM_CODE.get(err.code, 500)
    return HTTPException(
        status_code=status,
        detail={"code": err.code, "message": err.message},
    )


class SessionCreate(BaseModel):
    mode: Literal["text", "voice"] = "text"


class SessionOut(BaseModel):
    id: str
    created_at: str
    mode: str


# ── App factory ───────────────────────────────────────────────────────
def create_app(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> FastAPI:
    """App factory — keeps imports side-effect free for tests.

    Per-app state (no module-level mutable singleton):
      app.state.settings       — Settings used by lifespan + /ready
      app.state.llm_client     — LLMClient shared by HTTP + WebSocket
      app.state.sessions       — SessionStore
      app.state.voice_runtime  — Daily bot + barge-in registry
      app.state.memory         — LettaMemoryService | None
      app.state.memory_client  — underlying MemoryClient | None
      app.state.memory_stack   — MemoryStack
      app.state.recall_store   — RecallStore | None
      app.state.archival       — ArchivalBackend | None
      app.state.episodic       — EpisodicStore | None
      app.state.sleeptime      — SleeptimeScheduler | None (memory consolidation)
      app.state.activity       — ActivityTracker (shared last-interaction clock)
      app.state.proactive      — Phase 4 ProactiveLoop | None
      app.state.schedule_store — ScheduleStore
      app.state.ws_hub         — ConnectionHub
      app.state.delivery       — NotificationDelivery
    """
    settings = settings or get_settings()
    app = FastAPI(
        title="FAE-v2 Backend",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.llm_client = llm_client or LLMClient(
        provider=OpenAICompatibleProvider()
    )
    app.state.sessions = SessionStore()
    app.state.voice_runtime = VoiceRuntime()
    app.state.memory = None
    app.state.memory_client = None
    app.state.memory_stack = MemoryStack()
    app.state.recall_store = None
    app.state.archival = None
    app.state.episodic = None
    app.state.sleeptime = None
    app.state.proactive = None
    app.state.ws_hub = ConnectionHub()
    app.state.schedule_store = ScheduleStore(_schedules_db_path(settings))
    app.state.activity = ActivityTracker(store=app.state.schedule_store)
    _seed_builtin_jobs(app.state.schedule_store)
    app.state.delivery = NotificationDelivery(
        app.state.schedule_store,
        app.state.ws_hub,
        vapid_public_key=settings.vapid_public_key,
        vapid_private_key=settings.vapid_private_key,
        vapid_subject=settings.vapid_subject,
        notifications_enabled=settings.notifications_enabled,
    )
    skills_dir = (
        Path(settings.skills_dir) if settings.skills_dir else default_skills_dir()
    )
    state_path = Path(settings.skills_state_path)
    if not state_path.is_absolute():
        state_path = REPO_ROOT / state_path
    app.state.skills = SkillRuntime(
        skills_dir=skills_dir,
        state_path=state_path,
        max_active=settings.skills_max_active,
        enabled=settings.skills_enabled,
        repo_root=REPO_ROOT,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Checkpoint 1 endpoints ────────────────────────────────────────
    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe: the process is up and responding."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        """Readiness probe for always-on Core.

        Values use ok|down|off|skipped|misconfigured.
        Memory ``down`` → HTTP 503 and ``status=degraded``; Telegram
        misconfiguration alone does not fail the probe.
        """
        app_settings: Settings = request.app.state.settings
        memory: LettaMemoryService | None = getattr(
            request.app.state, "memory", None
        )
        letta_status = "skipped"
        if app_settings.letta_mode == "off":
            letta_status = "off"
        elif app_settings.letta_mode == "embedded":
            letta_status = "ok" if memory and memory.enabled else "down"
        else:
            client = memory.client if memory else None
            if client is not None and hasattr(client, "health"):
                letta_status = "ok" if await client.health() else "down"  # type: ignore[misc]
            elif memory and memory.enabled:
                letta_status = "ok"
            else:
                letta_status = "down"
        memory_status = letta_status

        proactive = getattr(request.app.state, "proactive", None)
        if not getattr(app_settings, "scheduler_enabled", False):
            scheduler_status = "off"
        elif isinstance(proactive, ProactiveLoop) and proactive._started:
            scheduler_status = "ok"
        else:
            scheduler_status = "down"

        if not getattr(app_settings, "telegram_enabled", True):
            telegram_status = "off"
        elif not telegram_ready(app_settings):
            telegram_status = "misconfigured"
        else:
            tg_task = getattr(request.app.state, "telegram_task", None)
            if tg_task is not None and not tg_task.done():
                telegram_status = "ok"
            else:
                telegram_status = "down"

        key = (
            (getattr(app_settings, "proactive_llm_api_key", "") or "").strip()
            or (getattr(app_settings, "dashscope_api_key", "") or "").strip()
        )
        proactive_llm_status = (
            "ok" if key and key != "unused" else "misconfigured"
        )

        overall = "degraded" if memory_status == "down" else "ready"
        payload = {
            "status": overall,
            "app": app_settings.app_name,
            "letta": letta_status,
            "memory": memory_status,
            "scheduler": scheduler_status,
            "telegram": telegram_status,
            "proactive_llm": proactive_llm_status,
        }
        code = 503 if memory_status == "down" else 200
        return JSONResponse(payload, status_code=code)

    # ── Checkpoint 2 endpoints ────────────────────────────────────────
    @app.post("/api/test-connection", response_model=dict[str, str])
    async def test_connection(
        config: LLMConfig,
        client: Annotated[LLMClient, Depends(get_llm_client)],
    ) -> dict[str, str]:
        """Send a 1-token probe to verify the provider is reachable
        and the API key is valid."""
        try:
            content = await client.test_connection(config)
        except LLMError as e:
            raise _llm_error_to_http(e) from e
        return {
            "status": "ok",
            "model": config.model,
            "echo": content,
        }

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(
        body: ChatRequest,
        request: Request,
        client: Annotated[LLMClient, Depends(get_llm_client)],
    ) -> ChatResponse:
        """Synchronous text-only chat completion. Used by the UI's
        "text fallback" mode and by the smoke tests in this checkpoint.

        For real-time streaming (the voice-orb chat panel), use the
        WebSocket endpoint /ws/chat instead.
        """
        memory: LettaMemoryService | None = getattr(
            request.app.state, "memory", None
        )
        skills_rt = getattr(request.app.state, "skills", None)
        # Single-user local default aligns with UI / proactive / consolidate.
        session_id = (body.session_id or "").strip() or "default"
        user_text = ""
        for msg in reversed(body.messages):
            if msg.role == "user":
                user_text = msg.content
                break
        try:
            settings = request.app.state.settings
            prepared, activation, default_city = await prepare_chat_request(
                body,
                session_id=session_id,
                memory=memory,
                skills=skills_rt if isinstance(skills_rt, SkillRuntime) else None,
                default_city=getattr(settings, "weather_default_city", "") or "",
                default_timezone=getattr(settings, "weather_default_timezone", "")
                or "",
            )
            from fae.agent.llm_turn import (
                activation_wants_subagent,
                apply_lazy_skill_tool,
            )
            from fae.scheduler.store import ScheduleStore as _ScheduleStore
            from fae.tools.weather import weather_likely

            early: str | None = None
            schedule_store = getattr(request.app.state, "schedule_store", None)
            sched = (
                schedule_store
                if (
                    isinstance(schedule_store, _ScheduleStore)
                    and settings.scheduler_enabled
                )
                else None
            )
            weather_on = bool(getattr(settings, "weather_enabled", True)) and (
                weather_likely(user_text) or "weather_briefing" in activation.active
            )

            subagent_on = bool(
                getattr(settings, "subagent_enabled", True)
            ) and activation_wants_subagent(
                activation,
                skills_rt if isinstance(skills_rt, SkillRuntime) else None,
            )
            tools_needed = bool(
                (isinstance(skills_rt, SkillRuntime) and activation.tools)
                or sched
                or weather_on
                or subagent_on
            )
            if tools_needed:
                prepared, activation, early = await apply_lazy_skill_tool(
                    client,
                    prepared,
                    activation,
                    skills_rt if isinstance(skills_rt, SkillRuntime) else None,
                    session_id=session_id,
                    schedule_store=sched,
                    weather_enabled=weather_on,
                    default_city=default_city,
                    memory=memory,
                    subagent_enabled=subagent_on,
                    subagent_timeout_s=float(
                        getattr(settings, "subagent_timeout_s", 60.0) or 60.0
                    ),
                )
                if early and "日程工具" in early:
                    proactive = getattr(request.app.state, "proactive", None)
                    if isinstance(proactive, ProactiveLoop):
                        proactive.resync()
            if early is not None:
                response = ChatResponse(
                    content=early,
                    model=prepared.config.model,
                    usage=None,
                )
            else:
                response = await client.chat(prepared)
            if memory is not None and memory.enabled and user_text:
                await memory.persist_turn(
                    session_id=session_id,
                    user_text=user_text,
                    assistant_text=response.content,
                )
            else:
                activity = getattr(request.app.state, "activity", None)
                if isinstance(activity, ActivityTracker):
                    activity.touch(session_id)
            return response
        except LLMError as e:
            raise _llm_error_to_http(e) from e

    # ── Phase 1.2: sessions stub ───────────────────────────────────────
    @app.post("/api/sessions", response_model=SessionOut)
    async def create_session(
        payload: SessionCreate,
        request: Request,
    ) -> SessionOut:
        store: SessionStore = request.app.state.sessions
        session = store.create(mode=payload.mode)
        return SessionOut(
            id=session.id, created_at=session.created_at, mode=session.mode
        )

    @app.get("/api/sessions", response_model=list[SessionOut])
    async def list_sessions(request: Request) -> list[SessionOut]:
        store: SessionStore = request.app.state.sessions
        return [
            SessionOut(id=s.id, created_at=s.created_at, mode=s.mode)
            for s in store.list()
        ]

    @app.get("/api/sessions/{session_id}", response_model=SessionOut)
    async def get_session(session_id: str, request: Request) -> SessionOut:
        store: SessionStore = request.app.state.sessions
        session = store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return SessionOut(
            id=session.id, created_at=session.created_at, mode=session.mode
        )

    # ── Checkpoint 3: WebSocket streaming chat ─────────────────────────
    app.include_router(ws_router)

    # ── Phase 1.3: text pipeline smoke ─────────────────────────────────
    app.include_router(pipeline_router)

    # ── Phase 1.4: voice session bootstrap ─────────────────────────────
    app.include_router(voice_router)

    # ── Local TTS ──────────────────────────────────────────────────────
    app.include_router(tts_router)
    if settings.tts_embed_stub:
        from fae.tts.stub_server import mount_stub_routes

        mount_stub_routes(app)
        logger.info(
            "Embedded TTS stub at /v1/audio/speech (set TTS_EMBED_STUB=false "
            "for a real local TTS server)"
        )

    # ── Phase 2: Memory browser ────────────────────────────────────────
    app.include_router(memory_router)

    # ── Phase 3: Skills ────────────────────────────────────────────────
    app.include_router(skills_router)

    # ── Phase 4: Schedules + notifications ─────────────────────────────
    app.include_router(schedules_router)
    app.include_router(scheduler_status_router)
    app.include_router(notifications_router)

    return app


# Module-level app for `uvicorn fae.api:app`
app = create_app()
