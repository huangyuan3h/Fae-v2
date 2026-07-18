"""Tests for /api/sessions and SessionStore."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.sessions import SessionStore


def test_session_store_create_get_list() -> None:
    store = SessionStore()
    a = store.create(mode="text")
    b = store.create(mode="voice")
    assert store.get(a.id) is a
    assert store.get("missing") is None
    ids = {s.id for s in store.list()}
    assert ids == {a.id, b.id}


def test_sessions_http_api() -> None:
    client = TestClient(create_app())
    created = client.post("/api/sessions", json={"mode": "voice"})
    assert created.status_code == 200
    sid = created.json()["id"]
    assert created.json()["mode"] == "voice"

    listed = client.get("/api/sessions")
    assert listed.status_code == 200
    assert any(s["id"] == sid for s in listed.json())

    got = client.get(f"/api/sessions/{sid}")
    assert got.status_code == 200
    assert got.json()["id"] == sid

    missing = client.get("/api/sessions/does-not-exist")
    assert missing.status_code == 404
