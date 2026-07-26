from __future__ import annotations

import json
from pathlib import Path

import pytest

from fae.agent_trace import (
    AgentTraceStore,
    KIND_SUBAGENT,
    KIND_TOOL,
    PHASE_DONE,
    PHASE_ERROR,
    PHASE_START,
    make_agent_trace_callback,
    new_turn_id,
)


def test_agent_trace_persists_tool_subagent_and_redacts(tmp_path: Path) -> None:
    store = AgentTraceStore(tmp_path / "trace.db")
    try:
        store.record_event(
            {
                "kind": "tool",
                "phase": PHASE_START,
                "name": "run_bash",
                "arguments": json.dumps({"command": "ls", "api_key": "secret"}),
            },
            turn_id="turn-1",
            session_id="session-1",
            channel="http",
        )
        store.record_event(
            {
                "kind": "tool",
                "phase": PHASE_DONE,
                "name": "run_bash",
                "ok": True,
                "result": "ok",
            },
            turn_id="turn-1",
            session_id="session-1",
            channel="http",
        )
        store.record_event(
            {
                "kind": KIND_SUBAGENT,
                "phase": PHASE_START,
                "name": "researcher",
                "task": "summarize",
            },
            turn_id="turn-1",
            session_id="session-1",
            channel="http",
        )
        store.record_event(
            {
                "kind": KIND_SUBAGENT,
                "phase": PHASE_ERROR,
                "name": "researcher",
                "ok": False,
                "error_code": "timeout",
            },
            turn_id="turn-1",
            session_id="session-1",
            channel="http",
        )

        events = store.list_events(session_id="session-1")
        kinds = [event.kind for event in events]
        assert kinds == [KIND_SUBAGENT, KIND_SUBAGENT, KIND_TOOL, KIND_TOOL]
        tool_done = next(e for e in events if e.kind == KIND_TOOL and e.phase == PHASE_DONE)
        subagent_err = next(e for e in events if e.kind == KIND_SUBAGENT and e.phase == PHASE_ERROR)
        assert tool_done.ok is True
        assert "secret" not in tool_done.payload  # redaction
        assert subagent_err.error_code == "timeout"
    finally:
        store.close()


def test_agent_trace_filters_and_pagination(tmp_path: Path) -> None:
    store = AgentTraceStore(tmp_path / "trace.db")
    try:
        for i in range(5):
            store.record_event(
                {
                    "kind": "tool",
                    "phase": "start",
                    "name": "read_file",
                    "arguments": json.dumps({"path": f"file-{i}"}),
                },
                turn_id=f"turn-{i}",
                session_id=f"sess-{i % 2}",
            )
        # session filter: 5 events split 2/3 across sess-0 / sess-1.
        sess_even = store.list_events(session_id="sess-0")
        assert len(sess_even) == 3
        assert all(event.session_id == "sess-0" for event in sess_even)

        by_turn = store.list_events(turn_id="turn-2")
        assert len(by_turn) == 1
        assert by_turn[0].turn_id == "turn-2"

        # cursor pagination: 5 events total, latest 2 then earliest 2.
        first_page = store.list_events(limit=2)
        assert len(first_page) == 2
        before_ts = min(event.started_at for event in first_page)
        second_page = store.list_events(limit=2, before=before_ts)
        assert len(second_page) == 2
        assert (
            {event.id for event in first_page}.isdisjoint(
                {event.id for event in second_page}
            )
        )

        assert len(store.list_events(kind="skill")) == 0
    finally:
        store.close()


def test_agent_trace_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "trace.db"
    store = AgentTraceStore(db_path)
    turn = new_turn_id()
    store.record_event(
        {"kind": "tool", "phase": "start", "name": "get_weather"},
        turn_id=turn,
        session_id="s1",
    )
    store.close()

    store2 = AgentTraceStore(db_path)
    try:
        events = store2.list_events(turn_id=turn)
        assert len(events) == 1
        assert events[0].name == "get_weather"
    finally:
        store2.close()


def test_agent_trace_callback_ignores_unknown_kind(tmp_path: Path) -> None:
    store = AgentTraceStore(tmp_path / "trace.db")
    try:
        callback = make_agent_trace_callback(
            store,
            turn_id="t",
            session_id="s",
            channel="http",
        )

        async def _run() -> None:
            await callback({"kind": "tool", "phase": "start", "name": "x"})
            await callback({"kind": "skill", "phase": "start", "name": "y"})
            await callback({"kind": "wat", "phase": "start", "name": "z"})
            await callback({"phase": "start", "name": "no-kind"})

        import asyncio
        asyncio.run(_run())
        events = store.list_events(turn_id="t")
        kinds = sorted({e.kind for e in events})
        assert kinds == ["skill", "tool"]
    finally:
        store.close()


@pytest.mark.parametrize(
    "event,persist",
    [
        ({"kind": "tool", "phase": "start", "name": "x"}, True),
        ({"kind": "tool", "phase": "start", "name": "x", "arguments": {"k": "v"}}, True),
        ({"kind": "tool", "phase": "done", "name": "x"}, True),
        ({"kind": "tool", "phase": "wat", "name": "x"}, False),
        ({"phase": "start", "name": "x"}, False),
    ],
)
def test_agent_trace_payload_round_trip(tmp_path: Path, event: dict, persist: bool) -> None:
    store = AgentTraceStore(tmp_path / "trace.db")
    try:
        store.record_event(event, turn_id="t", session_id="s")
        events = store.list_events()
        assert (len(events) == 1) is persist
    finally:
        store.close()


def test_agent_trace_normalizes_result_phase_with_duration(tmp_path: Path) -> None:
    store = AgentTraceStore(tmp_path / "trace.db")
    try:
        store.record_event(
            {"kind": "tool", "phase": "start", "name": "run_bash"},
            turn_id="turn-1",
            session_id="s",
        )
        import time as _t

        _t.sleep(0.01)
        # ``phase: result`` (live wire form) must persist as terminal
        # ``done`` when ok=true, and populate duration_ms from the matching
        # start row.
        store.record_event(
            {
                "kind": "tool",
                "phase": "result",
                "name": "run_bash",
                "ok": True,
                "result": "ok",
            },
            turn_id="turn-1",
            session_id="s",
        )
        events = store.list_events(turn_id="turn-1")
        assert [e.phase for e in events] == ["done", "start"]
        terminal = next(e for e in events if e.phase == "done")
        assert terminal.ok is True
        assert terminal.duration_ms is not None
        assert terminal.duration_ms > 0
        assert terminal.finished_at is not None

        # Result with ok=False should be persisted as error.
        store.record_event(
            {"kind": "tool", "phase": "start", "name": "write_file"},
            turn_id="turn-1",
            session_id="s",
        )
        store.record_event(
            {
                "kind": "tool",
                "phase": "result",
                "name": "write_file",
                "ok": False,
                "result": '{"ok":false,"error":"permission"}',
                "error_code": "permission_denied",
            },
            turn_id="turn-1",
            session_id="s",
        )
        events = store.list_events(turn_id="turn-1")
        err_terminal = next(e for e in events if e.phase == "error")
        assert err_terminal.ok is False
        assert err_terminal.error_code == "permission_denied"
    finally:
        store.close()
