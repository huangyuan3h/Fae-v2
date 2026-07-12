"""LLMClient — thin wrapper that holds a provider and exposes a single
async `chat` method. Centralises logging so callers (FastAPI handlers)
can map `LLMError` to HTTP responses in one place.
"""

from __future__ import annotations

import logging

from fae.llm.errors import LLMError
from fae.llm.provider import LLMProvider
from fae.llm.types import ChatMessage, ChatRequest, ChatResponse

logger = logging.getLogger("fae.llm")

__all__ = ["LLMClient", "LLMError"]


class LLMClient:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def chat(self, request: ChatRequest) -> ChatResponse:
        logger.debug(
            "LLM request: model=%s msgs=%d temp=%.2f",
            request.config.model,
            len(request.messages),
            request.temperature,
        )
        return await self._provider.chat(request)

    async def test_connection(self, config: ChatRequest.config.__class__) -> str:
        """Send a 1-token request to confirm the provider is reachable
        and the key is valid. Returns the model's echo (often empty)."""
        probe = ChatRequest(
            config=config,
            messages=[ChatMessage(role="user", content="ping")],
            max_tokens=1,
            temperature=0.0,
        )
        resp = await self._provider.chat(probe)
        return resp.content

