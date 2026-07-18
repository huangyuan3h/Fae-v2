"""Tests for TextPipelineBot + pipeline HTTP endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fae.api import create_app
from fae.llm import LLMClient, LLMConfig
from fae.llm.provider import FakeProvider
from fae.pipecat.bot import TextPipelineBot
from fae.pipecat.transport import LocalTransport


@pytest.mark.asyncio
async def test_text_pipeline_bot_emits_tokens_sentences_audio() -> None:
    fake = FakeProvider(tokens=["你好", "。", "世界"])
    transport = LocalTransport()
    bot = TextPipelineBot(LLMClient(provider=fake), transport=transport)
    config = LLMConfig(api_key="sk-test", model="fake")

    events = []
    async for ev in bot.run_turn("hi", config):
        events.append(ev)

    types = [e.type for e in events]
    assert "token" in types
    assert "sentence" in types
    assert "audio" in types
    assert types[-1] == "done"
    assert transport.sent_text  # at least one sentence forwarded
    assert any(e.content == "你好。" for e in events if e.type == "sentence")


@pytest.mark.asyncio
async def test_text_pipeline_bot_honours_barge_in() -> None:
    # Long token stream; interrupt after first token event.
    fake = FakeProvider(tokens=["a", "b", "c", "d", "e", "。"])
    bot = TextPipelineBot(LLMClient(provider=fake))
    config = LLMConfig(api_key="sk-test")

    events = []
    async for ev in bot.run_turn("hi", config):
        events.append(ev)
        if ev.type == "token" and len([e for e in events if e.type == "token"]) == 1:
            bot.barge_in.on_user_speech_during_playback()

    assert any(e.type == "interrupted" for e in events)
    assert not any(e.type == "done" for e in events)


def test_pipeline_text_http_endpoint() -> None:
    fake = FakeProvider(tokens=["Hi", "!"])
    app = create_app(llm_client=LLMClient(provider=fake))
    client = TestClient(app)

    resp = client.post(
        "/api/pipeline/text",
        json={
            "text": "hello",
            "config": {"base_url": "http://x", "api_key": "k", "model": "m"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_text"] == "Hi!"
    assert body["sentences"]
    assert body["events"][-1]["type"] == "done"
