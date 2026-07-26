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
    assert body.get("letta") == "off"
    assert body.get("memory") == "off"
    assert body.get("scheduler") == "off"
    assert body.get("telegram") == "misconfigured"
    assert body.get("proactive_llm") == "misconfigured"


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
    assert api_module.app.version == "0.6.0"


def test_lifespan_wires_tool_offloader_and_cleanup_task() -> None:
    """The lifespan must (a) construct a ``ToolOffloader`` with the
    configured TTL when offload is enabled, (b) start a periodic cleanup
    task, and (c) cleanly cancel it on shutdown."""
    from fae.agent.tool_offload import ToolOffloader
    from fae.config import Settings

    custom = Settings(
        app_name="fae-test-offload",
        log_level="WARNING",
        tool_offload_enabled=True,
        tool_offload_dir=".data/test-tool-offload-wiring",
        tool_offload_ttl_s=120.0,
        tool_offload_cleanup_interval_s=300.0,
    )
    app = create_app(settings=custom)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        offloader = app.state.tool_offloader
        cleanup_task = app.state.tool_offload_cleanup_task
        assert isinstance(offloader, ToolOffloader)
        assert offloader.ttl_s == 120.0
        assert cleanup_task is not None
        assert not cleanup_task.done()
    # Context exit must cancel the task.
    assert cleanup_task.cancelled() or cleanup_task.done()


def test_lifespan_disables_offload_when_settings_say_so() -> None:
    from fae.config import Settings

    custom = Settings(
        app_name="fae-test-offload-off",
        log_level="WARNING",
        tool_offload_enabled=False,
    )
    app = create_app(settings=custom)
    with TestClient(app):
        assert app.state.tool_offloader is None
        assert app.state.tool_offload_cleanup_task is None
