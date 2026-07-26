"""LLM provider implementations.

`LLMProvider` is a minimal Protocol — anything with async `chat` / `stream`
methods qualifies. Production uses `OpenAICompatibleProvider`; tests use
`FakeProvider` for hermetic, deterministic behaviour.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

# LengthFinishReasonError is not re-exported from the top-level package in
# every openai version. Import defensively so a missing symbol doesn't
# break import time.
try:
    from openai import LengthFinishReasonError  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover — only on stripped openai builds
    LengthFinishReasonError = None  # type: ignore[assignment,misc]

from fae.llm.errors import LLMError
from fae.llm.types import ChatRequest, ChatResponse, TokenUsage, ToolCall

logger = logging.getLogger("fae.llm")


def _thinking_extra_body(thinking: str) -> dict[str, object] | None:
    """Map LLMConfig.thinking → provider extra_body (MiniMax-compatible)."""
    if thinking == "disabled":
        return {"thinking": {"type": "disabled"}}
    if thinking == "adaptive":
        return {"thinking": {"type": "adaptive"}}
    return None


def _extra_body(cfg) -> dict[str, object] | None:
    """Combine thinking + prompt_cache_key into a single extra_body dict."""
    body = _thinking_extra_body(cfg.thinking)
    if cfg.prompt_cache_key:
        cache_body = {"prompt_cache_key": cfg.prompt_cache_key}
        if body is None:
            return cache_body
        body.update(cache_body)
    return body


def _extract_usage(resp_usage: object) -> TokenUsage | None:
    """Build a TokenUsage from the openai SDK response.usage object."""
    if resp_usage is None:
        return None
    prompt = getattr(resp_usage, "prompt_tokens", None)
    completion = getattr(resp_usage, "completion_tokens", None)
    total = getattr(resp_usage, "total_tokens", None)
    if prompt is None and completion is None and total is None:
        return None
    cached: int | None = None
    cache_creation: int | None = None
    details = getattr(resp_usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", None)
    cache_creation = getattr(resp_usage, "cache_creation_input_tokens", None)
    if cached is None:
        hit = getattr(resp_usage, "prompt_cache_hit_tokens", None)
        if hit is not None:
            cached = hit
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cached_tokens=cached,
        cache_creation_tokens=cache_creation,
    )


def _delta_reasoning_text(delta: object) -> str | None:
    """Extract incremental reasoning/thinking text from a stream delta."""
    if delta is None:
        return None
    for attr in ("reasoning_content", "reasoning"):
        val = getattr(delta, attr, None)
        if isinstance(val, str) and val:
            return val
    extra = getattr(delta, "model_extra", None)
    if isinstance(extra, dict):
        for key in ("reasoning_content", "reasoning"):
            val = extra.get(key)
            if isinstance(val, str) and val:
                return val
        details = extra.get("reasoning_details")
        if isinstance(details, list):
            parts: list[str] = []
            for item in details:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                else:
                    text = getattr(item, "text", None)
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "".join(parts)
    details = getattr(delta, "reasoning_details", None)
    if isinstance(details, list):
        parts = []
        for item in details:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "".join(parts)
    return None


async def _aclose(resource: object) -> None:
    """Best-effort close of an openai client or streaming response.

    The SDK's Stream.close() is sync; AsyncOpenAI.close() is a coroutine.
    Handle both shapes so callers never leak HTTP connections.
    """
    close = getattr(resource, "close", None)
    if close is None:
        return
    try:
        result = close()
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # noqa: BLE001 — best-effort cleanup
        logger.debug("resource close() raised", exc_info=True)


def _map_openai_error(
    e: BaseException,
    *,
    model: str,
    base_url: str,
    timeout_s: float,
) -> LLMError:
    """Normalise an openai SDK exception into a stable LLMError."""
    if isinstance(e, AuthenticationError):
        return LLMError(
            code="auth",
            message=f"Authentication failed for model '{model}': {e}",
        )
    if isinstance(e, PermissionDeniedError):
        return LLMError(
            code="forbidden",
            message=f"Permission denied for model '{model}': {e}",
        )
    if isinstance(e, NotFoundError):
        return LLMError(
            code="not_found",
            message=f"Model '{model}' not found at {base_url}: {e}",
        )
    if isinstance(e, RateLimitError):
        return LLMError(
            code="rate_limited",
            message=f"Rate limited by provider: {e}",
        )
    if isinstance(e, APITimeoutError):
        return LLMError(
            code="timeout",
            message=f"LLM request timed out after {timeout_s}s",
        )
    if isinstance(e, APIConnectionError):
        return LLMError(
            code="connection",
            message=f"Cannot reach LLM endpoint {base_url}: {e}",
        )
    if isinstance(e, BadRequestError):
        return LLMError(
            code="bad_request",
            message=f"LLM rejected request: {e}",
        )
    if LengthFinishReasonError is not None and isinstance(e, LengthFinishReasonError):
        return LLMError(
            code="length",
            message=f"LLM hit max_tokens limit: {e}",
        )
    if isinstance(e, APIError):
        logger.warning("Unclassified openai SDK error: %s", e)
        return LLMError(
            code="connection",
            message=f"LLM provider error: {e}",
        )
    logger.exception("Unexpected LLM error")
    return LLMError(
        code="unknown",
        message=f"Unexpected LLM error: {e}",
    )


@runtime_checkable
class LLMProvider(Protocol):
    """The minimum surface the rest of the app needs from an LLM backend."""

    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Yield content tokens as they arrive.

        Implementations MUST honour asyncio cancellation: if the consumer
        drops the iterator (e.g. via `asyncio.Task.cancel()`), the
        underlying network stream must be closed promptly.
        """
        ...


class OpenAICompatibleProvider:
    """Real provider for any OpenAI-compatible chat completions server
    (Qwen3 / DashScope compatible-mode, DeepSeek, vLLM, OpenAI, …).

    Both `chat` and `stream` use `AsyncOpenAI` so the FastAPI event loop
    is never blocked. A fresh client is built per call so we never hold a
    reference to a key longer than the request, and every path closes the
    client (and stream response) in a `finally` block.
    """

    def __init__(self, default_timeout_s: float = 10.0) -> None:
        self._default_timeout_s = default_timeout_s
        # Captured usage from the most recently completed stream. Cleared
        # at the start of every stream so callers can read it after the
        # generator finishes.
        self.last_stream_usage: TokenUsage | None = None

    def _client_for(self, request: ChatRequest) -> AsyncOpenAI:
        cfg = request.config
        return AsyncOpenAI(
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            timeout=self._default_timeout_s,
            default_headers=cfg.headers,
        )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        cfg = request.config
        client = self._client_for(request)
        try:
            kwargs: dict = {
                "model": cfg.model,
                "messages": [m.model_dump() for m in request.messages],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            }
            if request.tools:
                kwargs["tools"] = request.tools
                if request.tool_choice is not None:
                    kwargs["tool_choice"] = request.tool_choice
            extra = _extra_body(cfg)
            if extra:
                kwargs["extra_body"] = extra
            try:
                resp = await client.chat.completions.create(**kwargs)
            except Exception as e:  # noqa: BLE001 — normalised below
                raise _map_openai_error(
                    e,
                    model=cfg.model,
                    base_url=cfg.base_url,
                    timeout_s=self._default_timeout_s,
                ) from e

            if not resp.choices:
                raise LLMError(
                    code="empty_response",
                    message="LLM returned no choices",
                )
            message = resp.choices[0].message
            content = message.content or ""
            tool_calls: list[ToolCall] = []
            for tc in getattr(message, "tool_calls", None) or []:
                fn = getattr(tc, "function", None)
                if fn is None:
                    continue
                tool_calls.append(
                    ToolCall(
                        id=getattr(tc, "id", "") or "",
                        name=getattr(fn, "name", "") or "",
                        arguments=getattr(fn, "arguments", None) or "{}",
                    )
                )
            usage = _extract_usage(getattr(resp, "usage", None))
            return ChatResponse(
                content=content,
                model=resp.model,
                usage=usage,
                tool_calls=tool_calls,
            )
        finally:
            await _aclose(client)

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Stream completion tokens via the OpenAI async streaming API.

        Yields assistant content piece by piece. Cancellation closes both
        the streaming response and the underlying AsyncOpenAI client.

        Token usage is captured when the final chunk arrives (openai SDK
        streams usage as a separate choice) and stored on the response.
        """
        cfg = request.config
        client = self._client_for(request)
        response: object | None = None
        stream_usage: TokenUsage | None = None
        self.last_stream_usage = None
        try:
            create_kwargs: dict = {
                "model": cfg.model,
                "messages": [m.model_dump() for m in request.messages],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            extra = _extra_body(cfg)
            if extra:
                create_kwargs["extra_body"] = extra
            try:
                response = await client.chat.completions.create(**create_kwargs)
            except Exception as e:  # noqa: BLE001 — normalised below
                raise _map_openai_error(
                    e,
                    model=cfg.model,
                    base_url=cfg.base_url,
                    timeout_s=self._default_timeout_s,
                ) from e

            try:
                # MiniMax / Qwen may stream reasoning outside delta.content.
                # Wrap as <think> so the UI can show "思考中" and TTS skips it.
                in_reasoning = False
                async for chunk in response:  # type: ignore[union-attr]
                    if not chunk.choices:
                        # Final usage chunk (when stream_options.include_usage).
                        chunk_usage = getattr(chunk, "usage", None)
                        if chunk_usage is not None:
                            stream_usage = _extract_usage(chunk_usage)
                        continue
                    delta = chunk.choices[0].delta
                    reasoning = _delta_reasoning_text(delta)
                    piece = delta.content if delta and delta.content else None
                    if reasoning:
                        if not in_reasoning:
                            yield "<think>"
                            in_reasoning = True
                        yield reasoning
                    if piece:
                        if in_reasoning:
                            yield "</think>"
                            in_reasoning = False
                        yield piece
                if in_reasoning:
                    yield "</think>"
            except asyncio.CancelledError:
                logger.debug("Stream cancelled by caller")
                raise
            except APIError as e:
                logger.warning("Stream interrupted by openai error: %s", e)
                raise LLMError(
                    code="connection",
                    message=f"Stream interrupted: {e}",
                ) from e
            except Exception as e:  # noqa: BLE001
                logger.exception("Unexpected error during streaming")
                raise LLMError(
                    code="unknown",
                    message=f"Unexpected streaming error: {e}",
                ) from e
        finally:
            if response is not None:
                await _aclose(response)
            await _aclose(client)
            self.last_stream_usage = stream_usage


class FakeProvider:
    """Deterministic in-process provider. Used by tests.

    Configure behaviour via the constructor so each test owns its own
    canned responses and error injection.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        error: Exception | None = None,
        echo: bool = False,
        tokens: list[str] | None = None,
        tool_call_responses: list[list[ToolCall]] | None = None,
    ) -> None:
        # If `echo` is set, the provider echoes back the last user message
        # (handy for trivial "is the wire working" smoke tests).
        self._responses = list(responses or [])
        self._tokens = list(tokens or [])
        self._tool_call_responses = list(tool_call_responses or [])
        self._error = error
        self._echo = echo
        self.calls: list[ChatRequest] = []  # observability for tests
        self.stream_calls: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        tool_calls: list[ToolCall] = []
        if self._tool_call_responses:
            tool_calls = self._tool_call_responses.pop(0)
        if self._echo:
            last_user = next(
                (m.content for m in reversed(request.messages) if m.role == "user"),
                "",
            )
            return ChatResponse(
                content=last_user,
                model="fake-model",
                usage=None,
                tool_calls=tool_calls,
            )
        if not self._responses and not tool_calls:
            return ChatResponse(content="", model="fake-model", usage=None)
        content = self._responses.pop(0) if self._responses else ""
        return ChatResponse(
            content=content,
            model="fake-model",
            usage=None,
            tool_calls=tool_calls,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Yield the configured token list, one per loop tick.

        - If `error` is set, raise it on the FIRST token iteration (so
          callers can distinguish "stream started then failed" from
          "stream never started").
        - If `echo` is set, treat the last user message as the token
          list (one character at a time) for trivially observable output.
        - Cancellation propagates via CancelledError.
        """
        self.stream_calls.append(request)
        if self._echo:
            last_user = next(
                (m.content for m in reversed(request.messages) if m.role == "user"),
                "",
            )
            tokens = list(last_user)
        else:
            tokens = list(self._tokens)
        for tok in tokens:
            if self._error is not None:
                raise self._error
            # Yielding via sleep(0) lets the consumer's cancel() take
            # effect at each token boundary (vs. only at end-of-stream).
            await asyncio.sleep(0)
            yield tok
