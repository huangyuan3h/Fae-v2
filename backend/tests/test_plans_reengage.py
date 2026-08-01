"""Tests for the Plan Mode user-reengage flow (P1 follow-up).

Covers store-level helpers (`unblock_step(note=)`, `append_step_note`),
the `user_response_for_blocked_block` prompt-block helper, and the WS
inbound `plan_step_input` message handling that drives user-provided
answers from the FE back into the persisted plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fae.agent.plan_tools import (
    active_plan_as_prompt_block,
    dispatch_update_plan,
    find_blocked_steps,
    user_response_for_blocked_block,
)
from fae.plans import PlanStepStatus, PlanStore


@pytest.fixture()
def store(tmp_path: Path) -> PlanStore:
    s = PlanStore(tmp_path / "plans.db")
    yield s
    s.close()


def _create_two_step_plan(store: PlanStore, session_id: str = "s1") -> None:
    dispatch_update_plan(
        {
            "action": "create",
            "title": "Ship v1",
            "summary": "release",
            "steps": [
                {"title": "build", "acceptance": "compiles"},
                {"title": "deploy", "acceptance": "live"},
            ],
        },
        session_id=session_id,
        plan_store=store,
    )


def test_unblock_step_with_note_overwrites_existing_note(store: PlanStore) -> None:
    _create_two_step_plan(store)
    dispatch_update_plan(
        {"action": "block", "step_index": 0, "note": "need api key"},
        session_id="s1",
        plan_store=store,
    )
    plan = store.get_active_for_session("s1")
    step = plan.steps[0]
    assert step.status == PlanStepStatus.BLOCKED.value
    assert step.note == "need api key"

    updated = store.unblock_step(step.id, note="key is abc123")
    assert updated.status == PlanStepStatus.PENDING.value
    assert updated.note == "key is abc123"

    refreshed = store.get_active_for_session("s1")
    assert refreshed.steps[0].status == "pending"
    assert refreshed.steps[0].note == "key is abc123"


def test_unblock_step_without_note_preserves_existing(store: PlanStore) -> None:
    _create_two_step_plan(store)
    dispatch_update_plan(
        {"action": "block", "step_index": 0, "note": "need api key"},
        session_id="s1",
        plan_store=store,
    )
    step = store.get_active_for_session("s1").steps[0]
    updated = store.unblock_step(step.id)
    assert updated.status == "pending"
    assert updated.note == "need api key"


def test_append_step_note_does_not_change_status(store: PlanStore) -> None:
    _create_two_step_plan(store)
    plan = store.get_active_for_session("s1")
    step = plan.steps[0]
    assert step.status == "pending"
    updated = store.append_step_note(step.id, "user: rate limit hit, retrying in 1m")
    assert updated.status == "pending"
    assert updated.note == "user: rate limit hit, retrying in 1m"

    appended = store.append_step_note(step.id, "user: new value is X")
    assert appended.status == "pending"
    assert "rate limit hit" in appended.note
    assert "new value is X" in appended.note


def test_cancel_step_after_blocked_reaches_terminal(store: PlanStore) -> None:
    _create_two_step_plan(store)
    dispatch_update_plan(
        {"action": "block", "step_index": 0, "note": "no key"},
        session_id="s1",
        plan_store=store,
    )
    step = store.get_active_for_session("s1").steps[0]
    cancelled = store.cancel_step(step.id, note="aborted")
    assert cancelled.status == "cancelled"
    assert cancelled.note == "aborted"
    plan = store.get_active_for_session("s1")
    # step 0 cancelled, step 1 still pending → plan stays active.
    assert plan.status == "active"


def test_find_blocked_steps_returns_only_blocked(store: PlanStore) -> None:
    _create_two_step_plan(store)
    dispatch_update_plan(
        {"action": "block", "step_index": 0, "note": "no key"},
        session_id="s1",
        plan_store=store,
    )
    plan = store.get_active_for_session("s1")
    blocked = find_blocked_steps(plan)
    assert [s.index for s in blocked] == [0]
    assert blocked[0].note == "no key"


def test_find_blocked_steps_empty_for_completed_plan(store: PlanStore) -> None:
    dispatch_update_plan(
        {
            "action": "create",
            "title": "tiny",
            "summary": "",
            "steps": [{"title": "a"}],
        },
        session_id="s1",
        plan_store=store,
    )
    dispatch_update_plan(
        {"action": "complete", "step_index": 0},
        session_id="s1",
        plan_store=store,
    )
    plan = store.get_plan(store.list_plans_for_session("s1")[0].id)
    assert plan.status == "completed"
    assert find_blocked_steps(plan) == []


def test_user_response_for_blocked_block_includes_notes(store: PlanStore) -> None:
    _create_two_step_plan(store)
    dispatch_update_plan(
        {"action": "block", "step_index": 1, "note": "need approval"},
        session_id="s1",
        plan_store=store,
    )
    plan = store.get_active_for_session("s1")
    block = user_response_for_blocked_block(plan)
    assert "<user_response_for_blocked>" in block
    assert "step_index=1" in block
    assert "need approval" in block
    assert "update_plan(action=unblock" in block


def test_user_response_for_blocked_block_empty_when_no_block(store: PlanStore) -> None:
    _create_two_step_plan(store)
    plan = store.get_active_for_session("s1")
    assert user_response_for_blocked_block(plan) == ""


def test_active_plan_block_preserves_blocked_marker_for_llm(store: PlanStore) -> None:
    _create_two_step_plan(store)
    dispatch_update_plan(
        {"action": "block", "step_index": 0, "note": "no key"},
        session_id="s1",
        plan_store=store,
    )
    plan = store.get_active_for_session("s1")
    text = active_plan_as_prompt_block(plan)
    assert "[!] blocked" in text
    assert "no key" in text


def _stub_ws(store: PlanStore) -> tuple[Any, list[dict]]:
    from fastapi import WebSocket
    from starlette.websockets import WebSocketState

    sent: list[dict] = []

    class _StubWS:
        client_state = WebSocketState.CONNECTED

        @property
        def app(self):
            return type("_App", (), {"state": type("_State", (), {"plan_store": store})()})()

        async def send_json(self, payload):
            sent.append(payload)

    return _StubWS(), sent


def test_ws_plan_step_input_answer_unblocks_step(store: PlanStore) -> None:
    """Drive the WS handler synchronously to ensure end-to-end persistence."""
    from fae.api.ws import _handle_plan_step_input

    _create_two_step_plan(store)
    plan = store.get_active_for_session("s1")
    dispatch_update_plan(
        {"action": "block", "step_index": 0, "note": "need api key"},
        session_id="s1",
        plan_store=store,
    )

    ws, sent = _stub_ws(store)

    import asyncio
    asyncio.run(
        _handle_plan_step_input(
            ws,
            {
                "plan_id": plan.id,
                "step_index": 0,
                "input_text": "key=abc",
                "kind": "answer",
            },
        )
    )

    assert sent, "expected plan_step_input_ack frame"
    assert sent[0]["type"] == "plan_step_input_ack"
    assert sent[0]["kind"] == "answer"
    assert sent[0]["plan"]["status"] == "active"
    assert sent[0]["step"]["status"] == "pending"
    assert sent[0]["step"]["note"] == "key=abc"

    refreshed = store.get_active_for_session("s1")
    assert refreshed.steps[0].status == "pending"
    assert refreshed.steps[0].note == "key=abc"


def test_ws_plan_step_input_abort_cancels_step(store: PlanStore) -> None:
    from fae.api.ws import _handle_plan_step_input

    _create_two_step_plan(store)
    plan = store.get_active_for_session("s1")
    dispatch_update_plan(
        {"action": "block", "step_index": 0, "note": "no key"},
        session_id="s1",
        plan_store=store,
    )

    ws, sent = _stub_ws(store)

    import asyncio
    asyncio.run(
        _handle_plan_step_input(
            ws,
            {
                "plan_id": plan.id,
                "step_index": 0,
                "input_text": "",
                "kind": "abort",
            },
        )
    )

    assert sent[0]["step"]["status"] == "cancelled"
    refreshed = store.get_active_for_session("s1")
    assert refreshed.steps[0].status == "cancelled"


def test_ws_plan_step_input_answer_on_pending_appends_note(store: PlanStore) -> None:
    from fae.api.ws import _handle_plan_step_input

    _create_two_step_plan(store)
    plan = store.get_active_for_session("s1")

    ws, sent = _stub_ws(store)

    import asyncio
    asyncio.run(
        _handle_plan_step_input(
            ws,
            {
                "plan_id": plan.id,
                "step_index": 0,
                "input_text": "use staging env",
                "kind": "answer",
            },
        )
    )

    assert sent[0]["type"] == "plan_step_input_ack"
    assert sent[0]["step"]["status"] == "pending"
    assert "use staging env" in sent[0]["step"]["note"]


def test_ws_plan_step_input_rejects_completed_step(store: PlanStore) -> None:
    from fae.api.ws import _handle_plan_step_input

    _create_two_step_plan(store)
    plan = store.get_active_for_session("s1")
    dispatch_update_plan(
        {"action": "complete", "step_index": 0},
        session_id="s1",
        plan_store=store,
    )

    ws, sent = _stub_ws(store)

    import asyncio
    asyncio.run(
        _handle_plan_step_input(
            ws,
            {
                "plan_id": plan.id,
                "step_index": 0,
                "input_text": "x",
                "kind": "answer",
            },
        )
    )

    assert sent[0]["type"] == "error"
    assert sent[0]["code"] == "not_blocked"


def test_ws_plan_step_input_rejects_bad_kind(store: PlanStore) -> None:
    from fae.api.ws import _handle_plan_step_input

    _create_two_step_plan(store)
    plan = store.get_active_for_session("s1")

    ws, sent = _stub_ws(store)

    import asyncio
    asyncio.run(
        _handle_plan_step_input(
            ws,
            {
                "plan_id": plan.id,
                "step_index": 0,
                "input_text": "x",
                "kind": "nope",
            },
        )
    )

    assert sent[0]["type"] == "error"
    assert sent[0]["code"] == "bad_request"