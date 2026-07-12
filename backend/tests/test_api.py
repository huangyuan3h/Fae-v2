"""Tests for fae.api — FastAPI app factory and lifespan."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from fae import api as api_module
from fae.api import create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["app"] == "fae-v2"


def test_create_app_uses_provided_settings() -> None:
    """App factory accepts a pre-built Settings so tests can override fields."""
    from fae.config import Settings

    custom = Settings(app_name="fae-test", log_level="WARNING")
    client = TestClient(create_app(settings=custom))
    resp = client.get("/ready")
    assert resp.json()["app"] == "fae-test"


def test_lifespan_runs_startup_and_shutdown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TestClient as a context manager triggers the lifespan — exercises
    the startup / shutdown logging that the bare TestClient skips."""
    caplog.set_level(logging.INFO, logger="fae")
    app = create_app()
    with TestClient(app) as client:
        # While the app is "running" inside the lifespan context, requests work.
        assert client.get("/health").status_code == 200

    # Both startup and shutdown messages should have been logged.
    messages = [record.getMessage() for record in caplog.records]
    assert any("Starting fae-v2" in m for m in messages)
    assert any("Shutting down fae-v2" in m for m in messages)


def test_module_level_app_is_well_formed() -> None:
    """`uvicorn fae.api:app` must resolve to a working FastAPI instance."""
    # Trigger any lazy module-level work.
    _ = api_module.app
    assert api_module.app.title == "FAE-v2 Backend"
    assert api_module.app.version == "0.1.0"
