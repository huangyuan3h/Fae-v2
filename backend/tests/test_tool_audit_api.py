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
                "arguments": "{\"path\":\"README.md\"}",
            },
            session_id="api-session",
            channel="http",
        )
        response = client.get(
            "/api/tool-audit",
            params={"session_id": "api-session", "channel": "http"},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "api-call"
    assert body[0]["phase"] == "start"
