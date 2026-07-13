"""LLMClient — thin wrapper that holds a provider and exposes
`chat`, `stream`, and `test_connection` methods. Centralises logging so
callers (FastAPI handlers / WebSocket endpoints) can map `LLMError` to
HTTP responses / WS messages in one place.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fae.llm.errors import LLMError
from fae.llm.provider import LLMProvider
from fae.llm.types import ChatMessage, ChatRequest, ChatResponse, LLMConfig

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

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Yield assistant tokens as they arrive. Cancellation is honoured.

        The WebSocket layer wraps this and pushes each token to the client;
        if the client disconnects or sends a `cancel` message, the wrapping
        task is cancelled, which propagates through this iterator and
        into the openai SDK to release the HTTP connection.
        """
        logger.debug(
            "LLM stream: model=%s msgs=%d",
            request.config.model,
            len(request.messages),
        )
        async for token in self._provider.stream(request):
            yield token

    async def test_connection(self, config: LLMConfig) -> str:
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

