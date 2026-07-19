"""Tests for /api/test-connection and /api/chat endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fae.api import create_app
from fae.llm import LLMClient
from fae.llm.errors import LLMError
from fae.llm.provider import FakeProvider, OpenAICompatibleProvider


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def fake_client() -> LLMClient:
    return LLMClient(provider=FakeProvider(responses=["hello back"], echo=False))


@pytest.fixture
def app(fake_client: LLMClient):
    return create_app(llm_client=fake_client)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


# ── /api/test-connection ──────────────────────────────────────────────


def test_test_connection_success(client: TestClient) -> None:
    body = {
        "base_url": "https://example.com",
        "api_key": "sk-test",
        "model": "qwen-test",
    }
    resp = client.post("/api/test-connection", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["model"] == "qwen-test"


def test_test_connection_maps_auth_error_to_401() -> None:
    fake = FakeProvider(error=LLMError(code="auth", message="bad key"))
    app = create_app(llm_client=LLMClient(provider=fake))
    c = TestClient(app)

    resp = c.post(
        "/api/test-connection",
        json={"base_url": "https://x", "api_key": "k", "model": "m"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth"


def test_test_connection_maps_timeout_to_504() -> None:
    fake = FakeProvider(error=LLMError(code="timeout", message="slow"))
    app = create_app(llm_client=LLMClient(provider=fake))
    c = TestClient(app)

    resp = c.post(
        "/api/test-connection",
        json={"base_url": "https://x", "api_key": "k", "model": "m"},
    )
    assert resp.status_code == 504


def test_test_connection_rejects_empty_api_key(client: TestClient) -> None:
    """The endpoint uses LLMConfig which validates api_key length."""
    resp = client.post(
        "/api/test-connection",
        json={"base_url": "https://x", "api_key": "", "model": "m"},
    )
    assert resp.status_code == 422


def test_create_app_binds_llm_client_on_app_state() -> None:
    """Each create_app() owns its own LLMClient on app.state — no globals."""
    app_a = create_app()
    app_b = create_app()
    assert app_a.state.llm_client is not app_b.state.llm_client
    assert isinstance(app_a.state.llm_client._provider, OpenAICompatibleProvider)

    injected = LLMClient(provider=FakeProvider())
    app_c = create_app(llm_client=injected)
    assert app_c.state.llm_client is injected


# ── /api/chat ─────────────────────────────────────────────────────────


def test_chat_returns_assistant_message(client: TestClient) -> None:
    resp = client.post(
        "/api/chat",
        json={
            "config": {
                "base_url": "https://x",
                "api_key": "k",
                "model": "m",
            },
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "hello back"
    assert body["model"] == "fake-model"


def test_chat_maps_rate_limited_to_429() -> None:
    fake = FakeProvider(error=LLMError(code="rate_limited", message="slow down"))
    app = create_app(llm_client=LLMClient(provider=fake))
    c = TestClient(app)

    resp = c.post(
        "/api/chat",
        json={
            "config": {"base_url": "x", "api_key": "k", "model": "m"},
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 429


def test_chat_maps_connection_to_502() -> None:
    fake = FakeProvider(error=LLMError(code="connection", message="down"))
    app = create_app(llm_client=LLMClient(provider=fake))
    c = TestClient(app)

    resp = c.post(
        "/api/chat",
        json={
            "config": {"base_url": "x", "api_key": "k", "model": "m"},
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 502


def test_chat_maps_unknown_error_to_500() -> None:
    fake = FakeProvider(error=LLMError(code="something_new", message="weird"))
    app = create_app(llm_client=LLMClient(provider=fake))
    c = TestClient(app)

    resp = c.post(
        "/api/chat",
        json={
            "config": {"base_url": "x", "api_key": "k", "model": "m"},
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 500
    assert resp.json()["detail"]["code"] == "something_new"


def test_chat_rejects_empty_messages(client: TestClient) -> None:
    resp = client.post(
        "/api/chat",
        json={
            "config": {"base_url": "x", "api_key": "k", "model": "m"},
            "messages": [],
        },
    )
    assert resp.status_code == 422
