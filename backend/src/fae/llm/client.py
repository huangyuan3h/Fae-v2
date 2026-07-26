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
from fae.llm.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LLMConfig,
    TokenUsage,
)

logger = logging.getLogger("fae.llm")

__all__ = ["LLMClient", "LLMError"]


def _accumulate(target: dict[str, int], usage: TokenUsage | None) -> None:
    if usage is None:
        return
    if usage.prompt_tokens is not None:
        target["prompt_tokens"] = target.get("prompt_tokens", 0) + usage.prompt_tokens
    if usage.completion_tokens is not None:
        target["completion_tokens"] = (
            target.get("completion_tokens", 0) + usage.completion_tokens
        )
    if usage.total_tokens is not None:
        target["total_tokens"] = target.get("total_tokens", 0) + usage.total_tokens
    if usage.cached_tokens is not None:
        target["cached_tokens"] = target.get("cached_tokens", 0) + usage.cached_tokens
    if usage.cache_creation_tokens is not None:
        target["cache_creation_tokens"] = (
            target.get("cache_creation_tokens", 0) + usage.cache_creation_tokens
        )
    target["calls"] = target.get("calls", 0) + 1


class LLMClient:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        # Usage captured from the most recently completed stream. Set on
        # the provider by OpenAICompatibleProvider.stream(); kept here as
        # a convenience accessor for callers that only have an LLMClient.
        self.last_stream_usage: TokenUsage | None = None
        # Process-local cumulative usage. Useful for /api/memory/stats
        # telemetry; counters reset only on process restart.
        self.usage_total: dict[str, int] = {}

    def usage_snapshot(self) -> dict[str, int]:
        """Return a copy of cumulative usage counters."""
        return dict(self.usage_total)

    def reset_usage(self) -> None:
        self.usage_total.clear()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        logger.debug(
            "LLM request: model=%s msgs=%d temp=%.2f",
            request.config.model,
            len(request.messages),
            request.temperature,
        )
        resp = await self._provider.chat(request)
        _accumulate(self.usage_total, resp.usage)
        return resp

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Yield assistant tokens as they arrive. Cancellation is honoured.

        The WebSocket layer wraps this and pushes each token to the client;
        if the client disconnects or sends a `cancel` message, the wrapping
        task is cancelled, which propagates through this iterator and
        into the openai SDK to release the HTTP connection.

        After the iterator finishes, ``self.last_stream_usage`` (and the
        underlying provider's ``last_stream_usage``) hold the most recent
        TokenUsage reported by the upstream, if any.
        """
        logger.debug(
            "LLM stream: model=%s msgs=%d",
            request.config.model,
            len(request.messages),
        )
        try:
            async for token in self._provider.stream(request):
                yield token
        finally:
            usage = getattr(self._provider, "last_stream_usage", None)
            self.last_stream_usage = usage
            _accumulate(self.usage_total, usage)

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

