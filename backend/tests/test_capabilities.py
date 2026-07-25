"""Tests for GET /api/capabilities and FAE_CLIENT_TOKEN (P7)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.config import Settings
from fae.llm import LLMClient
from fae.llm.provider import FakeProvider


def test_capabilities_shape() -> None:
    settings = Settings(dashscope_api_key="sk-x", skills_enabled=True)
    app = create_app(settings=settings)
    client = TestClient(app)
    resp = client.get("/api/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channels"]["web_ws"] is True
    assert body["channels"]["http_chat"] is True
    assert "telegram" in body["channels"]
    assert body["modes"]["text"] is True
    assert isinstance(body["tools"], list)
    assert "get_weather" in body["tools"]
    assert "read_file" in body["tools"]
    assert "git_diff" in body["tools"]
    assert body["tool_runtime"]["filesystem_enabled"] is False
    assert body["llm"]["server_configured"] is True
    assert body["auth"]["client_token_required"] is False
    assert body["status"]["proactive_llm"] == "ok"


def test_capabilities_public_when_token_required() -> None:
    settings = Settings(fae_client_token="secret")
    app = create_app(settings=settings)
    client = TestClient(app)
    assert client.get("/api/capabilities").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_token_rejects_unauthenticated_chat() -> None:
    fake = FakeProvider(responses=["ok"], echo=False)
    settings = Settings(fae_client_token="secret", dashscope_api_key="sk")
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    client = TestClient(app)
    resp = client.post(
        "/api/chat",
        json={
            "config": {"api_key": ""},
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 401


def test_token_accepts_bearer() -> None:
    fake = FakeProvider(responses=["ok"], echo=False)
    settings = Settings(fae_client_token="secret", dashscope_api_key="sk")
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    client = TestClient(app)
    resp = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer secret"},
        json={
            "config": {"api_key": ""},
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "ok"


def test_token_accepts_query_param() -> None:
    fake = FakeProvider(responses=["ok"], echo=False)
    settings = Settings(fae_client_token="secret", dashscope_api_key="sk")
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    client = TestClient(app)
    resp = client.post(
        "/api/chat?access_token=secret",
        json={
            "config": {"api_key": ""},
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
