"""Tests for /api/test-connection and /api/chat endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fae import api as api_module
from fae.api import create_app
from fae.llm import ChatMessage, ChatRequest, LLMClient, LLMConfig
from fae.llm.errors import LLMError
from fae.llm.provider import FakeProvider


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def fake_client() -> LLMClient:
    """LLMClient backed by a FakeProvider. Reset the module singleton
    around each test so create_app() picks up our injection."""
    api_module._default_client = None
    return LLMClient(provider=FakeProvider(responses=["hello back"], echo=False))


@pytest.fixture
def app(fake_client: LLMClient):
    api_module._default_client = None
    return create_app(llm_client=fake_client)


@pytest.fixture
def client(app) -> TestClient:  # noqa: ARG001 — app dependency
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
    api_module._default_client = None
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
    api_module._default_client = None
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


def test_default_llm_client_is_created_on_demand() -> None:
    """If no client is injected, get_llm_client() builds a real one
    (used in production; tests should usually inject a fake)."""
    api_module._default_client = None
    c1 = api_module.get_llm_client()
    c2 = api_module.get_llm_client()
    # Singleton: same instance every time.
    assert c1 is c2
    # And it wraps a real OpenAICompatibleProvider.
    from fae.llm.provider import OpenAICompatibleProvider

    assert isinstance(c1._provider, OpenAICompatibleProvider)
    # Cleanup for next test.
    api_module._default_client = None


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
    api_module._default_client = None
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
    api_module._default_client = None
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
    api_module._default_client = None
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
