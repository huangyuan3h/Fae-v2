from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from fae.agent_trace import PHASE_START, new_turn_id
from fae.api import create_app
from fae.config import Settings


def _build_app(tmp_path) -> tuple[Any, Any]:
    settings = Settings(
        letta_mode="off",
        scheduler_enabled=False,
        tool_audit_db_path=str(tmp_path / "audit.db"),
        agent_trace_db_path=str(tmp_path / "trace.db"),
    )
    return create_app(settings=settings), settings


def test_agent_trace_api_filters_and_paginate(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        store = app.state.agent_trace
        audit = app.state.tool_audit
        turn = new_turn_id()
        store.record_event(
            {
                "kind": "tool",
                "phase": PHASE_START,
                "name": "read_file",
                "arguments": json.dumps({"path": "README.md"}),
            },
            turn_id=turn,
            session_id="api-session",
            channel="http",
        )
        audit.record_event(
            {
                "phase": PHASE_START,
                "id": "audit-call",
                "name": "read_file",
                "arguments": "{\"path\":\"README.md\"}",
            },
            session_id="api-session",
            channel="http",
        )
        resp = client.get(
            "/api/agent-trace",
            params={"session_id": "api-session", "turn_id": turn, "kind": "tool"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["turn_id"] == turn
    assert body[0]["kind"] == "tool"
    assert body[0]["name"] == "read_file"


def test_agent_trace_api_returns_empty_when_store_missing(tmp_path) -> None:
    app, _ = _build_app(tmp_path)
    with TestClient(app) as client:
        app.state.agent_trace = None
        resp = client.get("/api/agent-trace")
    assert resp.status_code == 200
    assert resp.json() == []
