from __future__ import annotations

import json
from pathlib import Path

from fae.tool_audit import ToolAuditStore


def test_tool_audit_round_trip_redacts_and_updates(tmp_path: Path) -> None:
    store = ToolAuditStore(tmp_path / "audit.db")
    try:
        started = store.record_event(
            {
                "type": "tool",
                "phase": "start",
                "id": "call-1",
                "name": "run_bash",
                "arguments": json.dumps(
                    {"command": "curl", "api_key": "secret-value"}
                ),
            },
            session_id="session-1",
            channel="ws",
            channel_id="connection-1",
            turn_id="turn-A",
        )
        assert started.phase == "start"
        assert started.ok is None
        assert started.turn_id == "turn-A"

        finished = store.record_event(
            {
                "type": "tool",
                "phase": "result",
                "id": "call-1",
                "name": "run_bash",
                "ok": False,
                "result": json.dumps(
                    {"ok": False, "error": "command_not_allowed", "token": "secret"}
                ),
            },
            session_id="session-1",
            channel="ws",
            channel_id="connection-1",
        )
        assert finished.phase == "error"
        assert finished.ok is False
        assert finished.error_code == "command_not_allowed"
        assert "secret-value" not in finished.arguments
        assert "secret" not in finished.result
        assert finished.duration_ms is not None
        assert finished.turn_id == "turn-A"

        events = store.list_events(session_id="session-1", channel="ws")
        assert len(events) == 1
        assert events[0].id == "call-1"
        assert events[0].channel_id == "connection-1"
        assert events[0].turn_id == "turn-A"

        # Filtering by turn_id is honored.
        assert len(store.list_events(turn_id="turn-A")) == 1
        assert len(store.list_events(turn_id="turn-Z")) == 0
    finally:
        store.close()


def test_tool_audit_filters_and_missing_completion(tmp_path: Path) -> None:
    store = ToolAuditStore(tmp_path / "audit.db")
    try:
        store.record_event(
            {"phase": "start", "id": "call-1", "name": "read_file"},
            session_id="one",
            channel="http",
        )
        event = store.record_event(
            {
                "phase": "result",
                "id": "call-2",
                "name": "get_weather",
                "ok": True,
                "result": "ok",
            },
            session_id="two",
            channel="telegram",
        )
        assert event.phase == "done"
        assert store.list_events(session_id="one", phase="start")[0].tool_name == "read_file"
        assert store.list_events(tool_name="get_weather", channel="telegram")[0].ok is True
        assert store.list_events(limit=1)[0].id == "call-2"
    finally:
        store.close()
