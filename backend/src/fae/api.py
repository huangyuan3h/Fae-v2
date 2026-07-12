"""FastAPI entry point.

Checkpoint 1: /health, /ready.
Checkpoint 2: /api/test-connection, /api/chat (text-only LLM).
Voice / WebSocket endpoints land in later checkpoints.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from fae.config import Settings, get_settings
from fae.llm import (
    ChatRequest,
    ChatResponse,
    LLMClient,
    LLMConfig,
    LLMError,
    OpenAICompatibleProvider,
)

logger = logging.getLogger("fae")


# ── Provider singletons ───────────────────────────────────────────────
# The client is stateless (a new OpenAI client is built per request from
# the user-supplied config), so it's safe to keep a single instance for
# the app's lifetime. Tests can override `get_llm_client` to inject fakes.

_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """FastAPI dependency: returns the singleton LLM client.

    Replace the underlying provider here when wiring up the full voice
    pipeline in a later checkpoint.
    """
    global _default_client
    if _default_client is None:
        _default_client = LLMClient(provider=OpenAICompatibleProvider())
    return _default_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks.

    - Validate config at startup so misconfig fails loudly, not on first request.
    - Place to wire up Pipecat transport, Letta client, scheduler, etc. later.
    """
    settings = get_settings()
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


# ── App factory ───────────────────────────────────────────────────────
def create_app(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> FastAPI:
    """App factory — keeps imports side-effect free for tests."""
    settings = settings or get_settings()
    app = FastAPI(
        title="FAE-v2 Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Override the default client if the caller injected one (tests do this).
    if llm_client is not None:
        global _default_client
        _default_client = llm_client

    # ── Checkpoint 1 endpoints ────────────────────────────────────────
    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe: the process is up and responding."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        """Readiness probe: config loaded and (later) downstream deps reachable."""
        return {"status": "ready", "app": settings.app_name}

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

        The streaming variant (used for the voice-orb chat panel) lands
        in Checkpoint 3 alongside the WebSocket transport.
        """
        try:
            return await client.chat(body)
        except LLMError as e:
            raise _llm_error_to_http(e) from e

    return app


# Module-level app for `uvicorn fae.api:app`
app = create_app()
