"""FastAPI entry point.

Checkpoint 1: /health, /ready.
Checkpoint 2: /api/test-connection, /api/chat (text-only LLM).
Checkpoint 3: /ws/chat (streaming WebSocket chat).
Phase 1.2/1.3: /api/sessions, /api/pipeline/text (text pipeline smoke).
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from fae.api.deps import get_llm_client
from fae.agent.prepare import prepare_chat_request
from fae.agent.skills_loader import default_skills_dir
from fae.agent.skills_runtime import SkillRuntime
from fae.api.pipeline import router as pipeline_router
from fae.api.skills import router as skills_router
from fae.api.tts import router as tts_router
from fae.api.voice import router as voice_router
from fae.api.ws import router as ws_router
from pathlib import Path

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
from fae.memory.core_budget import core_stats_from_client
from fae.memory.factory import MemoryStack, create_memory_stack
from fae.memory.schemas import FactIn
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.sessions import SessionStore
from fae.voice_runtime import VoiceRuntime

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

    # Skills runtime is created in create_app (available without lifespan).

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
            if stack.client is not None:
                app.state.memory = LettaMemoryService(
                    stack.client,
                    archival=stack.archival,
                    compactor=stack.compactor,
                    episodic=stack.episodic,
                    on_persist=scheduler.touch if scheduler else None,
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

    yield

    runtime = getattr(app.state, "voice_runtime", None)
    if runtime is not None:
        await runtime.shutdown()
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
      app.state.sleeptime      — SleeptimeScheduler | None
    """
    settings = settings or get_settings()
    app = FastAPI(
        title="FAE-v2 Backend",
        version="0.1.0",
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
    async def ready(request: Request) -> dict[str, str]:
        """Readiness probe: config loaded; Letta status is informational."""
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
        return {
            "status": "ready",
            "app": app_settings.app_name,
            "letta": letta_status,
        }

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
        # Never share a global "http" bucket across anonymous callers.
        session_id = (body.session_id or "").strip() or str(uuid.uuid4())
        user_text = ""
        for msg in reversed(body.messages):
            if msg.role == "user":
                user_text = msg.content
                break
        try:
            prepared, activation = await prepare_chat_request(
                body,
                session_id=session_id,
                memory=memory,
                skills=skills_rt if isinstance(skills_rt, SkillRuntime) else None,
            )
            from fae.agent.llm_turn import apply_lazy_skill_tool

            early: str | None = None
            if isinstance(skills_rt, SkillRuntime) and activation.tools:
                prepared, activation, early = await apply_lazy_skill_tool(
                    client, prepared, activation, skills_rt
                )
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

    @app.get("/api/memory/stats")
    async def memory_stats(request: Request) -> dict:
        """Core block sizes, hot recall count, and archival health."""
        memory: LettaMemoryService | None = getattr(
            request.app.state, "memory", None
        )
        client = memory.client if memory else None
        recall = getattr(request.app.state, "recall_store", None)
        archival = getattr(request.app.state, "archival", None)
        core = await core_stats_from_client(client)
        archival_status = "off"
        if archival is not None:
            try:
                archival_status = await archival.health()
            except Exception:  # noqa: BLE001
                archival_status = "down"
        episodic = getattr(request.app.state, "episodic", None)
        return {
            "recall_turns": recall.total_hot() if recall is not None else 0,
            "core": core,
            "archival": archival_status,
            "events": episodic.count() if episodic is not None else 0,
            "sleeptime": (
                "on"
                if getattr(request.app.state, "sleeptime", None) is not None
                else "off"
            ),
        }

    @app.get("/api/memory/events")
    async def memory_events(
        request: Request,
        session_id: str | None = None,
        limit: int = 50,
        q: str | None = None,
    ) -> dict:
        """List episodic life events (optional session / text filter)."""
        episodic = getattr(request.app.state, "episodic", None)
        if episodic is None:
            raise HTTPException(status_code=503, detail="episodic memory unavailable")
        events = episodic.list_events(
            session_id=session_id, limit=limit, query=q
        )
        return {
            "events": [
                {
                    "id": e.id,
                    "session_id": e.session_id,
                    "kind": e.kind,
                    "summary": e.summary,
                    "raw_text": e.raw_text,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "links": [
                        {
                            "event_id": lk.event_id,
                            "target_kind": lk.target_kind,
                            "target_id": lk.target_id,
                        }
                        for lk in e.links
                    ],
                }
                for e in events
            ]
        }

    @app.get("/api/memory/facts")
    async def memory_list_facts(
        request: Request,
        limit: int = 50,
        q: str | None = None,
    ) -> dict:
        memory: LettaMemoryService | None = getattr(
            request.app.state, "memory", None
        )
        if memory is None or memory.client is None:
            raise HTTPException(status_code=503, detail="memory unavailable")
        facts = await memory.client.list_facts(limit=limit, query=q)
        return {
            "facts": [
                {
                    "id": f.id,
                    "content": f.content,
                    "tags": f.tags,
                    "session_id": f.session_id,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in facts
            ]
        }

    @app.post("/api/memory/facts")
    async def memory_create_fact(body: FactIn, request: Request) -> dict:
        memory: LettaMemoryService | None = getattr(
            request.app.state, "memory", None
        )
        if memory is None or memory.client is None:
            raise HTTPException(status_code=503, detail="memory unavailable")
        fact = await memory.client.save_fact(body)
        return {
            "id": fact.id,
            "content": fact.content,
            "tags": fact.tags,
            "session_id": fact.session_id,
            "created_at": fact.created_at.isoformat() if fact.created_at else None,
        }

    @app.patch("/api/memory/facts/{fact_id}")
    async def memory_update_fact(
        fact_id: str, body: FactIn, request: Request
    ) -> dict:
        memory: LettaMemoryService | None = getattr(
            request.app.state, "memory", None
        )
        if memory is None or memory.client is None:
            raise HTTPException(status_code=503, detail="memory unavailable")
        try:
            fact = await memory.client.update_fact(fact_id, body)
        except KeyError as e:
            raise HTTPException(status_code=404, detail="fact not found") from e
        return {
            "id": fact.id,
            "content": fact.content,
            "tags": fact.tags,
            "session_id": fact.session_id,
            "created_at": fact.created_at.isoformat() if fact.created_at else None,
        }

    @app.delete("/api/memory/facts/{fact_id}")
    async def memory_delete_fact(fact_id: str, request: Request) -> dict:
        memory: LettaMemoryService | None = getattr(
            request.app.state, "memory", None
        )
        if memory is None or memory.client is None:
            raise HTTPException(status_code=503, detail="memory unavailable")
        ok = await memory.client.delete_fact(fact_id)
        if not ok:
            raise HTTPException(status_code=404, detail="fact not found")
        return {"ok": True, "id": fact_id}

    @app.get("/api/memory/search")
    async def memory_search(
        request: Request,
        q: str,
        top_k: int = 10,
        session_id: str | None = None,
    ) -> dict:
        """Unified search across facts, archival, and episodic events."""
        memory: LettaMemoryService | None = getattr(
            request.app.state, "memory", None
        )
        if memory is None or memory.client is None:
            raise HTTPException(status_code=503, detail="memory unavailable")
        query = (q or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="q is required")
        facts = await memory.client.search(query, top_k=top_k)
        sid_filter = (session_id or "").strip() or None
        if sid_filter:
            facts = [
                f
                for f in facts
                if not f.session_id or f.session_id == sid_filter
            ]
        archival_hits = []
        if memory.archival is not None:
            archival_hits = await memory.archival.search(
                query, top_k=top_k, session_id=session_id
            )
        events = []
        episodic = getattr(request.app.state, "episodic", None)
        if episodic is not None:
            events = episodic.list_events(
                session_id=session_id, limit=top_k, query=query
            )
        return {
            "query": query,
            "facts": [
                {
                    "id": f.id,
                    "content": f.content,
                    "tags": f.tags,
                    "source": "fact",
                }
                for f in facts
            ],
            "archival": [
                {
                    "id": f.id,
                    "content": f.content,
                    "tags": f.tags,
                    "source": "archival",
                }
                for f in archival_hits
            ],
            "events": [
                {
                    "id": e.id,
                    "content": e.summary,
                    "kind": e.kind,
                    "source": "event",
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
        }

    @app.get("/api/memory/timeline")
    async def memory_timeline(
        request: Request,
        limit: int = 40,
        session_id: str | None = None,
    ) -> dict:
        """Merged timeline points for the memory browser chart."""
        memory: LettaMemoryService | None = getattr(
            request.app.state, "memory", None
        )
        if memory is None or memory.client is None:
            raise HTTPException(status_code=503, detail="memory unavailable")
        points: list[dict] = []
        facts = await memory.client.list_facts(limit=limit)
        sid_filter = (session_id or "").strip() or None
        for f in facts:
            if sid_filter and f.session_id and f.session_id != sid_filter:
                continue
            points.append(
                {
                    "id": f.id,
                    "kind": "fact",
                    "label": f.content[:80],
                    "at": f.created_at.isoformat() if f.created_at else None,
                    "tags": f.tags,
                }
            )
        episodic = getattr(request.app.state, "episodic", None)
        if episodic is not None:
            for e in episodic.list_events(session_id=session_id, limit=limit):
                points.append(
                    {
                        "id": e.id,
                        "kind": "event",
                        "label": e.summary[:80],
                        "at": e.created_at.isoformat() if e.created_at else None,
                        "tags": [e.kind],
                    }
                )
        points.sort(key=lambda p: p.get("at") or "", reverse=True)
        return {"points": points[:limit]}

    @app.post("/api/memory/consolidate")
    async def memory_consolidate(
        request: Request,
        session_id: str = "default",
    ) -> dict:
        """Trigger sleeptime consolidation for a session (smoke / ops)."""
        scheduler = getattr(request.app.state, "sleeptime", None)
        if not isinstance(scheduler, SleeptimeScheduler):
            # Allow on-demand consolidate even if background scheduler is off.
            stack: MemoryStack = getattr(
                request.app.state, "memory_stack", MemoryStack()
            )
            if stack.client is None or stack.recall is None:
                raise HTTPException(status_code=503, detail="memory unavailable")
            consolidator = MemoryConsolidator(
                stack.client,
                stack.recall,
                archival=stack.archival,
                compactor=stack.compactor,
                current_char_limit=request.app.state.settings.core_current_char_limit,
                max_runtime_s=request.app.state.settings.sleeptime_max_runtime_s,
            )
            result = await consolidator.consolidate(session_id)
        else:
            result = await scheduler.consolidate_now(session_id)
        return {
            "session_id": result.session_id,
            "summarized_turns": result.summarized_turns,
            "facts_saved": result.facts_saved,
            "current_updated": result.current_updated,
            "compacted": result.compacted,
            "skipped": result.skipped,
            "elapsed_s": round(result.elapsed_s, 3),
        }

    # ── Checkpoint 3: WebSocket streaming chat ─────────────────────────
    app.include_router(ws_router)

    # ── Phase 1.3: text pipeline smoke ─────────────────────────────────
    app.include_router(pipeline_router)

    # ── Phase 1.4: voice session bootstrap ─────────────────────────────
    app.include_router(voice_router)

    # ── Qwen3-TTS (no Daily required) ──────────────────────────────────
    app.include_router(tts_router)

    # ── Phase 3: Skills ────────────────────────────────────────────────
    app.include_router(skills_router)

    return app


# Module-level app for `uvicorn fae.api:app`
app = create_app()
