"""Shared FastAPI dependencies.

Reads per-app state set by `create_app()` so HTTP and WebSocket handlers
share the same LLMClient without module-level mutable singletons.

Uses `HTTPConnection` (base of both Request and WebSocket) so the same
dependency works for REST routes and `/ws/chat`.
"""

from __future__ import annotations

from starlette.requests import HTTPConnection

from fae.llm import LLMClient
from fae.pipecat.services.letta_memory import LettaMemoryService


def get_llm_client(conn: HTTPConnection) -> LLMClient:
    """Resolve the LLMClient bound to this FastAPI application instance."""
    client = getattr(conn.app.state, "llm_client", None)
    if client is None:
        raise RuntimeError(
            "LLMClient not configured on app.state — create_app() must set it"
        )
    return client


def get_memory_service(conn: HTTPConnection) -> LettaMemoryService | None:
    """Optional memory service — None when Letta / embedded store is off."""
    memory = getattr(conn.app.state, "memory", None)
    if memory is None:
        return None
    if isinstance(memory, LettaMemoryService):
        return memory
    return None
