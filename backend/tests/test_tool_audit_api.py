from __future__ import annotations

from fastapi.testclient import TestClient

from fae.api import create_app
from fae.config import Settings


def test_tool_audit_api_filters_by_session(tmp_path) -> None:
    app = create_app(
        settings=Settings(
            letta_mode="off",
            scheduler_enabled=False,
            tool_audit_db_path=str(tmp_path / "audit.db"),
        )
    )
    with TestClient(app) as client:
        app.state.tool_audit.record_event(
            {
                "phase": "start",
                "id": "api-call",
                "name": "read_file",
                "arguments": '{"path":"README.md"}',
            },
            session_id="api-session",
            channel="http",
            turn_id="turn-A",
        )
        response = client.get(
            "/api/tool-audit",
            params={"session_id": "api-session", "channel": "http"},
        )
        filtered = client.get(
            "/api/tool-audit",
            params={"turn_id": "turn-A"},
        )
        absent = client.get(
            "/api/tool-audit",
            params={"turn_id": "turn-Z"},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "api-call"
    assert body[0]["phase"] == "start"
    # approval_id and turn_id must round-trip through the API model.
    assert body[0]["turn_id"] == "turn-A"
    assert body[0].get("approval_id") is None

    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert absent.status_code == 200
    assert absent.json() == []


def test_tool_audit_api_round_trips_approval_id(tmp_path) -> None:
    app = create_app(
        settings=Settings(
            letta_mode="off",
            scheduler_enabled=False,
            tool_audit_db_path=str(tmp_path / "audit-id.db"),
        )
    )
    with TestClient(app) as client:
        app.state.tool_audit.record_event(
            {
                "phase": "start",
                "id": "approval-call",
                "name": "run_bash",
                "arguments": '{"command":"rm -rf /"}',
                "approval_status": "approved",
                "approval_id": "appr-42",
            },
            session_id="api-id",
            channel="ws",
        )
        response = client.get("/api/tool-audit", params={"session_id": "api-id"})
    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "approval-call"
    assert body[0]["approval_id"] == "appr-42"
