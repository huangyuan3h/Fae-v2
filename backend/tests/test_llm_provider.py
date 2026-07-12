"""Tests for fae.llm.provider — FakeProvider + OpenAICompatibleProvider error mapping."""

from __future__ import annotations

import httpx
import pytest
from openai import (
    APIConnectionError,
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
