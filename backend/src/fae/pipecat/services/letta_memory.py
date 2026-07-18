"""Memory injector shared by browser WS, HTTP chat, and Daily."""

from __future__ import annotations

import logging

from fae.llm.types import ChatMessage, ChatRequest
from fae.memory.fact_extract import facts_from_turn
from fae.memory.protocol import MemoryClient
from fae.memory.schemas import FactIn

logger = logging.getLogger("fae.memory.service")

_MEMORY_TAG_OPEN = "<fae_memory>"
_MEMORY_TAG_CLOSE = "</fae_memory>"


class LettaMemoryService:
    """Fetch / persist memories around an LLM turn."""

    def __init__(self, client: MemoryClient | None = None) -> None:
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> MemoryClient | None:
        return self._client

    async def recall_context(
        self,
        query: str,
        *,
        session_id: str | None = None,
        top_k: int = 10,
    ) -> str:
        if self._client is None:
            return ""
        try:
            return await self._client.recall_for_prompt(
                query,
                session_id=session_id,
                top_k=top_k,
                recent_limit=10,
            )
        except Exception:  # noqa: BLE001
            logger.exception("recall_context failed")
            return ""

    def inject_into_request(self, request: ChatRequest, memory_text: str) -> ChatRequest:
        """Return a copy of request with memory as a leading system message."""
        text = (memory_text or "").strip()
        if not text:
            return request
        block = (
            f"{_MEMORY_TAG_OPEN}\n"
            "The following are durable memories and recent conversation. "
            "Use them when the user asks about prior topics or identity.\n"
            f"{text}\n"
            f"{_MEMORY_TAG_CLOSE}"
        )
        messages = [ChatMessage(role="system", content=block), *request.messages]
        return request.model_copy(update={"messages": messages})

    def memory_system_message(self, memory_text: str) -> dict[str, str] | None:
        """Build a system message dict for Daily LLMContext."""
        text = (memory_text or "").strip()
        if not text:
            return None
        return {
            "role": "system",
            "content": (
                f"{_MEMORY_TAG_OPEN}\n"
                "The following are durable memories and recent conversation. "
                "Use them when the user asks about prior topics or identity.\n"
                f"{text}\n"
                f"{_MEMORY_TAG_CLOSE}"
            ),
        }

    async def prepare_request(
        self,
        request: ChatRequest,
        *,
        session_id: str | None = None,
    ) -> ChatRequest:
        user_text = _last_user_text(request)
        memory = await self.recall_context(user_text, session_id=session_id)
        return self.inject_into_request(request, memory)

    async def persist_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        if self._client is None:
            return
        try:
            await self._client.append_recall(session_id, user_text, assistant_text)
            profile, facts = facts_from_turn(
                user_text=user_text,
                assistant_text=assistant_text,
                session_id=session_id or None,
            )
            if profile is not None:
                await self._client.update_user(profile)
            for fact in facts:
                await self._client.save_fact(fact)
            # Index user utterance for keyword recall (M2-2).
            trimmed = (user_text or "").strip()
            if trimmed and len(trimmed) >= 2:
                await self._client.save_fact(
                    FactIn(
                        content=trimmed,
                        tags=["utterance"],
                        session_id=session_id or None,
                    )
                )
        except Exception:  # noqa: BLE001
            logger.exception("persist_turn failed session=%s", session_id)


def _last_user_text(request: ChatRequest) -> str:
    for msg in reversed(request.messages):
        if msg.role == "user":
            return msg.content
    return ""
