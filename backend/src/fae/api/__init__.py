"""FastAPI entry point.

Checkpoint 1: /health, /ready.
Checkpoint 2: /api/test-connection, /api/chat (text-only LLM).
Checkpoint 3: /ws/chat (streaming WebSocket chat).
Phase 1.2/1.3: /api/sessions, /api/pipeline/text (text pipeline smoke).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from fae.api.deps import get_llm_client
from fae.api.pipeline import router as pipeline_router
from fae.api.voice import router as voice_router
from fae.api.ws import router as ws_router
from fae.config import Settings, get_settings
from fae.llm import (
    ChatRequest,
    ChatResponse,
    LLMClient,
    LLMConfig,
    LLMError,
    OpenAICompatibleProvider,
)
from fae.sessions import SessionStore

logger = logging.getLogger("fae")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks.

    - Log the settings bound on app.state (set by create_app).
    - Place to wire up Pipecat transport, Letta client, scheduler, etc. later.
    """
    settings: Settings = app.state.settings
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)
    yield
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
      app.state.settings    — Settings used by lifespan + /ready
      app.state.llm_client  — LLMClient shared by HTTP + WebSocket
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
        """Readiness probe: config loaded and (later) downstream deps reachable."""
        app_settings: Settings = request.app.state.settings
        return {"status": "ready", "app": app_settings.app_name}

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
        client: Annotated[LLMClient, Depends(get_llm_client)],
    ) -> ChatResponse:
        """Synchronous text-only chat completion. Used by the UI's
        "text fallback" mode and by the smoke tests in this checkpoint.

        For real-time streaming (the voice-orb chat panel), use the
        WebSocket endpoint /ws/chat instead.
        """
        try:
            return await client.chat(body)
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

    return app


# Module-level app for `uvicorn fae.api:app`
app = create_app()
