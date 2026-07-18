"""Pipecat-facing memory injector (Phase 2.2 — scaffold).

Both browser (`Qwen3LLMService`) and Daily (`OpenAILLMService`) paths should
call `recall_context()` before the LLM turn so Letta injection stays single-sourced.
"""

from __future__ import annotations

from fae.memory.letta_client import LettaMemoryClient


class LettaMemoryService:
    """Fetch top-k recall memories for a session turn."""

    def __init__(self, client: LettaMemoryClient | None = None) -> None:
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def recall_context(
        self,
        query: str,
        *,
        session_id: str | None = None,
        top_k: int = 10,
    ) -> str:
        """Return text to prepend / inject into the LLM system prompt."""
        _ = session_id
        if self._client is None:
            return ""
        return await self._client.recall_for_prompt(query, top_k=top_k)

    async def persist_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        """Write the completed turn into Recall Memory (Phase 2.2)."""
        _ = (session_id, user_text, assistant_text)
        if self._client is None:
            return
        raise NotImplementedError("Phase 2.2: persist_turn → Letta recall")
