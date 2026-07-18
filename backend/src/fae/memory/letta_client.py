"""Letta REST client (Phase 2.1 — scaffold).

Implements the surface used by tools / Pipecat injection. Methods raise
`NotImplementedError` until the Letta server + agent bootstrap land.
"""

from __future__ import annotations

import logging
from typing import Any

from fae.memory.schemas import FactIn, FactOut, UserProfile

logger = logging.getLogger("fae.memory.letta")


class LettaMemoryClient:
    """Thin async wrapper around Letta's HTTP API."""

    def __init__(self, base_url: str, *, agent_name: str = "fae-main") -> None:
        self.base_url = base_url.rstrip("/")
        self.agent_name = agent_name
        self._agent_id: str | None = None

    @property
    def agent_id(self) -> str | None:
        return self._agent_id

    async def ensure_agent(self) -> str:
        """Create or resolve the `fae-main` agent; return agent_id."""
        raise NotImplementedError("Phase 2.1: bootstrap Letta agent fae-main")

    async def save_fact(self, fact: FactIn) -> FactOut:
        raise NotImplementedError("Phase 2.1: memory_save_fact")

    async def search(self, query: str, *, top_k: int = 10) -> list[FactOut]:
        raise NotImplementedError("Phase 2.1: memory_search")

    async def update_user(self, profile: UserProfile) -> UserProfile:
        raise NotImplementedError("Phase 2.1: memory_update_user")

    async def recall_for_prompt(self, query: str, *, top_k: int = 10) -> str:
        """Return a short block of relevant memories for LLM system injection."""
        _ = (query, top_k)
        raise NotImplementedError("Phase 2.2: recall injection")

    async def close(self) -> None:
        """Release HTTP resources (no-op until aiohttp/httpx session exists)."""
        logger.debug("LettaMemoryClient.close base_url=%s", self.base_url)


# Tool names from DEVELOPMENT_PLAN 2.1 — implement as Letta tools later.
MEMORY_TOOLS: tuple[str, ...] = (
    "memory_save_fact",
    "memory_search",
    "memory_update_user",
)


def memory_tool_stubs() -> list[dict[str, Any]]:
    """OpenAI-style tool definitions for future agent registration."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"Stub for {name} (Phase 2.1)",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in MEMORY_TOOLS
    ]
