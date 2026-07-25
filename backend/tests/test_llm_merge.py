"""Tests for merge_llm_config / merge_chat_request (P7)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fae.api import create_app
from fae.channels.bridge import (
    MissingServerLLMError,
    merge_chat_request,
    merge_llm_config,
)
from fae.config import Settings
from fae.llm import ChatMessage, ChatRequest, LLMClient, LLMConfig
from fae.llm.provider import FakeProvider


def test_merge_uses_server_key_when_client_empty() -> None:
    settings = Settings(dashscope_api_key="sk-server", proactive_llm_model="qwen-plus")
    cfg = merge_llm_config(LLMConfig(api_key="", model=""), settings)
    assert cfg.api_key == "sk-server"
    assert cfg.model == "qwen-plus"


def test_merge_client_key_overrides_server() -> None:
    settings = Settings(dashscope_api_key="sk-server")
    cfg = merge_llm_config(
        LLMConfig(api_key="sk-client", base_url="http://local/v1", model="local"),
        settings,
    )
    assert cfg.api_key == "sk-client"
    assert cfg.base_url == "http://local/v1"
    assert cfg.model == "local"


def test_merge_raises_when_no_key() -> None:
    settings = Settings(dashscope_api_key="", proactive_llm_api_key="")
    with pytest.raises(MissingServerLLMError):
        merge_llm_config(LLMConfig(api_key=""), settings)


def test_merge_chat_request() -> None:
    settings = Settings(dashscope_api_key="sk-server")
    body = ChatRequest(
        config=LLMConfig(api_key=""),
        messages=[ChatMessage(role="user", content="hi")],
    )
    merged = merge_chat_request(body, settings)
    assert merged.config.api_key == "sk-server"


def test_chat_without_client_key_uses_server() -> None:
    fake = FakeProvider(responses=["ok"], echo=False)
    settings = Settings(dashscope_api_key="sk-server")
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    client = TestClient(app)
    resp = client.post(
        "/api/chat",
        json={
            "config": {"base_url": "", "api_key": "", "model": ""},
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "ok"


def test_chat_without_any_key_returns_503() -> None:
    fake = FakeProvider(responses=["ok"], echo=False)
    settings = Settings(dashscope_api_key="", proactive_llm_api_key="")
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    client = TestClient(app)
    resp = client.post(
        "/api/chat",
        json={
            "config": {"api_key": ""},
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "no_llm"


def test_test_connection_empty_key_uses_server() -> None:
    fake = FakeProvider(responses=["pong"], echo=False)
    settings = Settings(dashscope_api_key="sk-server", proactive_llm_model="m")
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    client = TestClient(app)
    resp = client.post(
        "/api/test-connection",
        json={"base_url": "", "api_key": "", "model": ""},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["model"] == "m"
