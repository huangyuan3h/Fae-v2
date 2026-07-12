"""Smoke tests for health / readiness endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fae.api import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_returns_app_name() -> None:
    client = TestClient(create_app())
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["app"] == "fae-v2"
