"""FastAPI entry point.

Checkpoint 1: minimal HTTP surface — just /health and /ready.
Voice / WebSocket endpoints land in later checkpoints.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fae.config import Settings, get_settings

logger = logging.getLogger("fae")


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


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory — keeps imports side-effect free for tests."""
    settings = settings or get_settings()
    app = FastAPI(
        title="FAE-v2 Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe: the process is up and responding."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        """Readiness probe: config loaded and (later) downstream deps reachable."""
        # In Checkpoint 1 we only assert config was loaded.
        return {"status": "ready", "app": settings.app_name}

    return app


# Module-level app for `uvicorn fae.api:app`
app = create_app()
