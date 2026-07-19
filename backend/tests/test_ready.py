"""Tests for GET /ready component fields (P6)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.config import Settings


def test_ready_without_telegram_token() -> None:
    """No Telegram credentials → telegram=misconfigured; process still ready."""
    client = TestClient(create_app())
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["memory"] == "off"
    assert body["letta"] == "off"
    assert body["scheduler"] == "off"
    assert body["telegram"] == "misconfigured"
    assert body["proactive_llm"] == "misconfigured"


def test_ready_telegram_explicitly_off() -> None:
    custom = Settings(telegram_enabled=False)
    client = TestClient(create_app(settings=custom))
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["telegram"] == "off"


def test_ready_fields_with_fake_server_keys() -> None:
    """Server LLM key + Telegram settings present → fields populated."""
    custom = Settings(
        telegram_bot_token="fake-token",
        telegram_chat_id="12345",
        telegram_enabled=True,
        dashscope_api_key="sk-test-key",
        scheduler_enabled=False,
        letta_mode="off",
    )
    client = TestClient(create_app(settings=custom))
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["memory"] == "off"
    assert body["scheduler"] == "off"
    # Lifespan starts the poll task when telegram_ready; TestClient runs lifespan.
    assert body["telegram"] in ("ok", "down")
    assert body["proactive_llm"] == "ok"
    assert set(body) >= {
        "status",
        "app",
        "letta",
        "memory",
        "scheduler",
        "telegram",
        "proactive_llm",
    }


def test_ready_memory_down_returns_503() -> None:
    """Embedded memory configured but unavailable → 503 degraded."""
    from types import SimpleNamespace

    custom = Settings(letta_mode="embedded", scheduler_enabled=False)
    app = create_app(settings=custom)

    with TestClient(app) as client:
        client.app.state.memory = SimpleNamespace(enabled=False, client=None)
        resp = client.get("/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["memory"] == "down"
        assert body["letta"] == "down"
