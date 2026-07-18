"""Tests for /api/voice/session."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fae.api import create_app


def test_voice_session_returns_browser_mode() -> None:
    client = TestClient(create_app())
    resp = client.post("/api/voice/session", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "browser"
    assert body["sessionId"]
