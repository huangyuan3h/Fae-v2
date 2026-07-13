"""Tests for fae.llm.provider — FakeProvider + OpenAICompatibleProvider error mapping."""

from __future__ import annotations

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from fae.llm import ChatMessage, ChatRequest, LLMConfig, OpenAICompatibleProvider
from fae.llm.errors import LLMError
from fae.llm.provider import FakeProvider


# ── FakeProvider ──────────────────────────────────────────────────────


async def test_fake_provider_returns_queued_responses_in_order() -> None:
    fake = FakeProvider(responses=["first", "second", "third"])
    req = ChatRequest(
        config=LLMConfig(api_key="sk-test"),
        messages=[ChatMessage(role="user", content="hi")],
    )

    a = await fake.chat(req)
    b = await fake.chat(req)
    c = await fake.chat(req)

    assert a.content == "first"
    assert b.content == "second"
    assert c.content == "third"


async def test_fake_provider_records_calls_for_observability() -> None:
    fake = FakeProvider(responses=["ok"])
    req = ChatRequest(
        config=LLMConfig(api_key="sk-test", model="qwen-test"),
        messages=[ChatMessage(role="user", content="hi")],
    )
    await fake.chat(req)
    assert len(fake.calls) == 1
    assert fake.calls[0].config.model == "qwen-test"


async def test_fake_provider_echo_mode() -> None:
    fake = FakeProvider(echo=True)
    req = ChatRequest(
        config=LLMConfig(api_key="sk-test"),
        messages=[
            ChatMessage(role="system", content="be terse"),
            ChatMessage(role="user", content="hello world"),
        ],
    )
    resp = await fake.chat(req)
    assert resp.content == "hello world"


async def test_fake_provider_empty_queue_returns_blank() -> None:
    fake = FakeProvider()
    resp = await fake.chat(
        ChatRequest(
            config=LLMConfig(api_key="sk-test"),
            messages=[ChatMessage(role="user", content="hi")],
        )
    )
    assert resp.content == ""


async def test_fake_provider_propagates_injected_error() -> None:
    sentinel = LLMError(code="custom", message="boom")
    fake = FakeProvider(error=sentinel)
    with pytest.raises(LLMError) as ei:
        await fake.chat(
            ChatRequest(
                config=LLMConfig(api_key="sk-test"),
                messages=[ChatMessage(role="user", content="hi")],
            )
        )
    assert ei.value.code == "custom"


# ── OpenAICompatibleProvider error mapping ────────────────────────────
# We never call the network. We construct a provider and invoke `.chat`
# with a bogus base_url to force the openai client to raise, then assert
# the mapping to LLMError.code. The point of these tests is to confirm
# our translation layer handles every documented openai error class.


def _request() -> ChatRequest:
    return ChatRequest(
        config=LLMConfig(
            base_url="http://127.0.0.1:1",  # always-refused port
            api_key="sk-bogus",
            model="fake-model",
        ),
        messages=[ChatMessage(role="user", content="hi")],
    )


async def test_openai_provider_maps_auth_error() -> None:
    """Auth error code path: we monkey-patch the OpenAI client to raise."""

    class _StubCompletions:
        def create(self, **_kw):  # noqa: ANN001
            raise AuthenticationError(
                message="bad key",
                response=httpx.Response(
                    status_code=401, request=httpx.Request("POST", "http://test")
                ),
                body=None,
            )

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    provider = OpenAICompatibleProvider()
    # Inject the stub via the provider's internal client slot.
    # The provider builds a new client per request, so we monkey-patch
    # the OpenAI class itself.
    import fae.llm.provider as provider_mod

    original_openai = provider_mod.OpenAI
    provider_mod.OpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        with pytest.raises(LLMError) as ei:
            await provider.chat(_request())
    finally:
        provider_mod.OpenAI = original_openai

    assert ei.value.code == "auth"


_KNOWN_ERROR_CASES = [
    (lambda: PermissionDeniedError(message="no", response=_fake_response(403), body=None), "forbidden"),
    (lambda: NotFoundError(message="missing", response=_fake_response(404), body=None), "not_found"),
    (lambda: RateLimitError(message="slow", response=_fake_response(429), body=None), "rate_limited"),
    (lambda: APITimeoutError(request=_fake_request()), "timeout"),
    (lambda: APIConnectionError(request=_fake_request()), "connection"),
    (lambda: BadRequestError(message="bad", response=_fake_response(400), body=None), "bad_request"),
]


def _fake_response(status_code: int = 500) -> httpx.Response:
    """Build a minimal httpx.Response for openai's exception classes."""
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "http://test"),
    )


def _fake_request() -> httpx.Request:
    return httpx.Request("POST", "http://test")


@pytest.mark.parametrize("exc_factory,expected_code", _KNOWN_ERROR_CASES)
async def test_openai_provider_maps_known_errors(
    exc_factory, expected_code: str
) -> None:
    exc = exc_factory()

    class _StubCompletions:
        def create(self, **_kw):  # noqa: ANN001
            raise exc

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    import fae.llm.provider as provider_mod

    original_openai = provider_mod.OpenAI
    provider_mod.OpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        with pytest.raises(LLMError) as ei:
            await OpenAICompatibleProvider().chat(_request())
    finally:
        provider_mod.OpenAI = original_openai

    assert ei.value.code == expected_code


async def test_openai_provider_maps_unknown_error() -> None:
    class _StubCompletions:
        def create(self, **_kw):  # noqa: ANN001
            raise RuntimeError("kaboom")

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    import fae.llm.provider as provider_mod

    original_openai = provider_mod.OpenAI
    provider_mod.OpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        with pytest.raises(LLMError) as ei:
            await OpenAICompatibleProvider().chat(_request())
    finally:
        provider_mod.OpenAI = original_openai

    assert ei.value.code == "unknown"
    assert "kaboom" in ei.value.message


async def test_openai_provider_empty_choices_raises() -> None:
    class _StubMessage:
        content = "ignored"

    class _StubChoice:
        message = _StubMessage()

    class _StubResp:
        choices: list = []
        model = "x"
        usage = None

    class _StubCompletions:
        def create(self, **_kw):  # noqa: ANN001
            return _StubResp()

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    import fae.llm.provider as provider_mod

    original_openai = provider_mod.OpenAI
    provider_mod.OpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        with pytest.raises(LLMError) as ei:
            await OpenAICompatibleProvider().chat(_request())
    finally:
        provider_mod.OpenAI = original_openai

    assert ei.value.code == "empty_response"


async def test_openai_provider_returns_usage_when_present() -> None:
    """When the response includes usage stats, the provider surfaces them."""

    class _StubMessage:
        content = "hi back"

    class _StubChoice:
        message = _StubMessage()

    class _StubUsage:
        prompt_tokens = 11
        completion_tokens = 22
        total_tokens = 33

    class _StubResp:
        choices = [_StubChoice()]
        model = "qwen3-test"
        usage = _StubUsage()

    class _StubCompletions:
        def create(self, **_kw):  # noqa: ANN001
            return _StubResp()

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    import fae.llm.provider as provider_mod

    original_openai = provider_mod.OpenAI
    provider_mod.OpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        resp = await OpenAICompatibleProvider().chat(_request())
    finally:
        provider_mod.OpenAI = original_openai

    assert resp.content == "hi back"
    assert resp.model == "qwen3-test"
    assert resp.usage == {
        "prompt_tokens": 11,
        "completion_tokens": 22,
        "total_tokens": 33,
    }


# ── FakeProvider.stream() ────────────────────────────────────────────


async def test_fake_provider_stream_yields_configured_tokens() -> None:
    fake = FakeProvider(tokens=["你", "好", "，", "世界"])
    req = ChatRequest(
        config=LLMConfig(api_key="sk-test"),
        messages=[ChatMessage(role="user", content="hi")],
    )

    collected: list[str] = []
    async for token in fake.stream(req):
        collected.append(token)

    assert collected == ["你", "好", "，", "世界"]
    # stream_calls records the request for observability.
    assert len(fake.stream_calls) == 1


async def test_fake_provider_stream_with_no_tokens_completes_immediately() -> None:
    fake = FakeProvider()
    req = ChatRequest(
        config=LLMConfig(api_key="sk-test"),
        messages=[ChatMessage(role="user", content="hi")],
    )

    collected: list[str] = []
    async for token in fake.stream(req):
        collected.append(token)

    assert collected == []


async def test_fake_provider_stream_echo_mode() -> None:
    """When echo=True, stream yields chars of the last user message."""
    fake = FakeProvider(echo=True)
    req = ChatRequest(
        config=LLMConfig(api_key="sk-test"),
        messages=[
            ChatMessage(role="system", content="be terse"),
            ChatMessage(role="user", content="abc"),
        ],
    )

    collected: list[str] = []
    async for token in fake.stream(req):
        collected.append(token)

    assert collected == ["a", "b", "c"]


async def test_fake_provider_stream_propagates_injected_error() -> None:
    """An injected error is raised on the first iteration, before any token."""
    err = LLMError(code="auth", message="bad key")
    fake = FakeProvider(tokens=["ok", "fail", "after"], error=err)
    req = ChatRequest(
        config=LLMConfig(api_key="sk-test"),
        messages=[ChatMessage(role="user", content="hi")],
    )

    collected: list[str] = []
    with pytest.raises(LLMError) as ei:
        async for token in fake.stream(req):
            collected.append(token)

    # The error fires before the first yield, so the consumer sees no tokens.
    assert collected == []
    assert ei.value.code == "auth"


async def test_fake_provider_stream_cancellation_stops_iteration() -> None:
    """Cancelling the consumer mid-stream must stop the provider cleanly."""
    import asyncio as _asyncio

    fake = FakeProvider(tokens=["a", "b", "c", "d", "e"])

    async def consume_two() -> list[str]:
        req = ChatRequest(
            config=LLMConfig(api_key="sk-test"),
            messages=[ChatMessage(role="user", content="hi")],
        )
        out: list[str] = []
        async for token in fake.stream(req):
            out.append(token)
            if len(out) >= 2:
                # Self-cancel by raising CancelledError into the task.
                raise _asyncio.CancelledError()
        return out

    with pytest.raises(_asyncio.CancelledError):
        await consume_two()


# ── OpenAICompatibleProvider.stream() error mapping ───────────────────


async def test_openai_provider_stream_maps_auth_error() -> None:
    class _StubCompletions:
        async def create(self, **_kw):  # noqa: ANN001
            raise AuthenticationError(
                message="bad key",
                response=httpx.Response(
                    status_code=401, request=httpx.Request("POST", "http://test")
                ),
                body=None,
            )

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    import fae.llm.provider as provider_mod

    original = provider_mod.AsyncOpenAI
    provider_mod.AsyncOpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        gen = OpenAICompatibleProvider().stream(_request())
        with pytest.raises(LLMError) as ei:
            await gen.__anext__()
    finally:
        provider_mod.AsyncOpenAI = original

    assert ei.value.code == "auth"


async def test_openai_provider_stream_maps_timeout_error() -> None:
    class _StubCompletions:
        async def create(self, **_kw):  # noqa: ANN001
            raise APITimeoutError(request=_fake_request())

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    import fae.llm.provider as provider_mod

    original = provider_mod.AsyncOpenAI
    provider_mod.AsyncOpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        gen = OpenAICompatibleProvider().stream(_request())
        with pytest.raises(LLMError) as ei:
            await gen.__anext__()
    finally:
        provider_mod.AsyncOpenAI = original

    assert ei.value.code == "timeout"


async def test_openai_provider_stream_maps_unknown_error() -> None:
    class _StubCompletions:
        async def create(self, **_kw):  # noqa: ANN001
            raise RuntimeError("kaboom")

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    import fae.llm.provider as provider_mod

    original = provider_mod.AsyncOpenAI
    provider_mod.AsyncOpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        gen = OpenAICompatibleProvider().stream(_request())
        with pytest.raises(LLMError) as ei:
            await gen.__anext__()
    finally:
        provider_mod.AsyncOpenAI = original

    assert ei.value.code == "unknown"


# ── OpenAICompatibleProvider.stream() happy path + cancellation ───────


class _StubDelta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _StubChoice:
    def __init__(self, content: str | None) -> None:
        self.delta = _StubDelta(content)


class _StubChunk:
    def __init__(self, content: str | None) -> None:
        self.choices = [_StubChoice(content)]


class _StubStreamResponse:
    """Async-iterable stub mimicking openai's streaming response.

    openai's Stream.close() is sync (returns None), so the stub mirrors
    that — the provider's `_close_stream` helper handles both shapes.
    """

    def __init__(self, chunks: list[_StubChunk], delay_s: float = 0.01) -> None:
        self._chunks = list(chunks)
        self._delay_s = delay_s
        self.closed = False

    def __aiter__(self) -> "_StubStreamResponse":
        return self

    async def __anext__(self) -> _StubChunk:
        import asyncio as _a
        if self._delay_s:
            await _a.sleep(self._delay_s)
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    def close(self) -> None:
        self.closed = True


def _stub_async_client(streaming_response: _StubStreamResponse) -> object:
    class _StubCompletions:
        async def create(self, **_kw):  # noqa: ANN001
            return streaming_response

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    return _StubClient()


async def test_openai_provider_stream_yields_tokens() -> None:
    response = _StubStreamResponse(
        [_StubChunk("你"), _StubChunk("好"), _StubChunk(None), _StubChunk("！")]
    )
    import fae.llm.provider as provider_mod

    original = provider_mod.AsyncOpenAI
    provider_mod.AsyncOpenAI = lambda **_kw: _stub_async_client(response)  # type: ignore[assignment]
    try:
        tokens: list[str] = []
        async for tok in OpenAICompatibleProvider().stream(_request()):
            tokens.append(tok)
    finally:
        provider_mod.AsyncOpenAI = original

    # None-delta chunks are skipped (tool-call frames etc).
    assert tokens == ["你", "好", "！"]


async def test_openai_provider_stream_cancellation_closes_response() -> None:
    """Cancelling the consumer via Task.cancel() must close the openai response.

    Mirror how the WebSocket endpoint cancels an in-flight stream on
    client disconnect: spawn a consumer task, then cancel and await it.
    """
    import asyncio as _asyncio

    # 50 tokens with 20ms delay each → stream takes ~1s; cancel well before.
    response = _StubStreamResponse(
        [_StubChunk(c) for c in "abcdefghijklmnopqrstuvwxyz0123456789abcdefghij"],
        delay_s=0.02,
    )
    import fae.llm.provider as provider_mod

    original = provider_mod.AsyncOpenAI
    provider_mod.AsyncOpenAI = lambda **_kw: _stub_async_client(response)  # type: ignore[assignment]
    try:

        async def consume() -> None:
            async for _ in OpenAICompatibleProvider().stream(_request()):
                pass

        task = _asyncio.create_task(consume())
        # Let the consumer pull 2-3 tokens.
        await _asyncio.sleep(0.05)
        task.cancel()
        # Drain the cancelled task — expect CancelledError.
        with __import__("contextlib").suppress(_asyncio.CancelledError):
            await task
    finally:
        provider_mod.AsyncOpenAI = original

    assert response.closed is True


async def test_openai_provider_stream_mid_stream_api_error() -> None:
    """Errors raised mid-stream (not at create time) get normalised."""

    class _RaisingStream:
        def __aiter__(self) -> "_RaisingStream":
            return self

        async def __anext__(self) -> object:
            raise APIError(
                message="connection lost",
                request=httpx.Request("POST", "http://test"),
                body=None,
            )

        def close(self) -> None:
            pass

    response = _RaisingStream()
    import fae.llm.provider as provider_mod

    original = provider_mod.AsyncOpenAI
    provider_mod.AsyncOpenAI = lambda **_kw: _stub_async_client(response)  # type: ignore[assignment]
    try:
        with pytest.raises(LLMError) as ei:
            async for _ in OpenAICompatibleProvider().stream(_request()):
                pass
    finally:
        provider_mod.AsyncOpenAI = original

    assert ei.value.code == "connection"


async def test_openai_provider_maps_unclassified_api_error() -> None:
    """openai errors that don't match a specific subclass land in our
    catch-all APIError branch and get normalised to 'connection'."""

    from openai import APIError

    class _StubCompletions:
        def create(self, **_kw):  # noqa: ANN001
            raise APIError(
                message="some other failure",
                request=httpx.Request("POST", "http://test"),
                body=None,
            )

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    import fae.llm.provider as provider_mod

    original_openai = provider_mod.OpenAI
    provider_mod.OpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        with pytest.raises(LLMError) as ei:
            await OpenAICompatibleProvider().chat(_request())
    finally:
        provider_mod.OpenAI = original_openai

    assert ei.value.code == "connection"


async def test_openai_provider_handles_null_content() -> None:
    """Some providers return null content (e.g. tool calls). We coerce to ''."""

    class _StubMessage:
        content = None

    class _StubChoice:
        message = _StubMessage()

    class _StubResp:
        choices = [_StubChoice()]
        model = "x"
        usage = None

    class _StubCompletions:
        def create(self, **_kw):  # noqa: ANN001
            return _StubResp()

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        chat = _StubChat()

    import fae.llm.provider as provider_mod

    original_openai = provider_mod.OpenAI
    provider_mod.OpenAI = lambda **_kw: _StubClient()  # type: ignore[assignment]
    try:
        resp = await OpenAICompatibleProvider().chat(_request())
    finally:
        provider_mod.OpenAI = original_openai

    assert resp.content == ""
    assert resp.usage is None
