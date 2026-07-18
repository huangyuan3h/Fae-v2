"""Tests for /api/voice/session."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.config import Settings


def test_voice_session_returns_browser_mode() -> None:
    client = TestClient(create_app())
    resp = client.post("/api/voice/session", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "browser"
    assert body["sessionId"]


def test_voice_session_prefer_daily_without_key_falls_back() -> None:
    settings = Settings(daily_api_key="")
    client = TestClient(create_app(settings=settings))
    resp = client.post("/api/voice/session", json={"prefer_daily": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "browser"
    assert "DAILY_API_KEY" in (body.get("detail") or "")


def test_barge_in_hook() -> None:
    client = TestClient(create_app())
    resp = client.post("/api/voice/barge-in", json={"session_id": "abc"})
    assert resp.status_code == 200
    assert resp.json()["action"] == "interrupted"
