"""Tests for fae.llm.client — LLMClient wrapper."""

from __future__ import annotations

from fae.llm import ChatMessage, ChatRequest, LLMClient, LLMConfig
from fae.llm.provider import FakeProvider


async def test_llm_client_chat_delegates_to_provider() -> None:
    fake = FakeProvider(responses=["pong"])
    client = LLMClient(provider=fake)

    req = ChatRequest(
        config=LLMConfig(api_key="sk-test"),
        messages=[ChatMessage(role="user", content="ping")],
    )
    resp = await client.chat(req)

    assert resp.content == "pong"
    assert len(fake.calls) == 1


async def test_llm_client_test_connection_sends_one_token_probe() -> None:
    """test_connection should send a 1-token, temp=0 probe to minimise cost."""
    fake = FakeProvider(echo=True)
    client = LLMClient(provider=fake)

    content = await client.test_connection(LLMConfig(api_key="sk-test"))

    # Echo mode returns the last user message; the probe sends "ping".
    assert content == "ping"
    probe = fake.calls[0]
    assert probe.max_tokens == 1
    assert probe.temperature == 0.0
    assert len(probe.messages) == 1
    assert probe.messages[0].content == "ping"


async def test_llm_client_propagates_provider_error() -> None:
    from fae.llm.errors import LLMError

    err = LLMError(code="auth", message="bad key")
    client = LLMClient(provider=FakeProvider(error=err))

    with __import__("pytest").raises(LLMError) as ei:
        await client.chat(
            ChatRequest(
                config=LLMConfig(api_key="sk-test"),
                messages=[ChatMessage(role="user", content="hi")],
            )
        )
    assert ei.value.code == "auth"
