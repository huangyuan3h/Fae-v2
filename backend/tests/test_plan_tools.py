"""Tests for the update_plan tool dispatcher."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from fae.agent.plan_tools import (
    PlanToolEvent,
    UPDATE_PLAN_TOOL,
    active_plan_as_prompt_block,
    dispatch_update_plan,
    inject_plan_directive,
    should_auto_plan,
)
from fae.llm.client import LLMClient
from fae.llm.provider import FakeProvider
from fae.llm.types import ChatMessage, ChatRequest, ChatResponse, LLMConfig
from fae.plans import PlanStore


@pytest.fixture()
def store(tmp_path: Path) -> PlanStore:
    s = PlanStore(tmp_path / "plans.db")
    yield s
    s.close()


def _capture_emitter():
    """Return (events, fn) — events is the list that gets appended."""
    events: list[PlanToolEvent] = []

    def emit(ev: PlanToolEvent):
        events.append(ev)
        # no await needed for sync emit
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
    return events, emit


def test_create_emits_plan_created(store: PlanStore) -> None:
    events, emit = _capture_emitter()
    dispatch_update_plan(
        {
            "action": "create",
            "title": "Ship v1",
            "summary": "release",
            "steps": [
                {"title": "build", "acceptance": "compiles"},
                {"title": "test", "acceptance": "pytest passes"},
            ],
        },
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    assert len(events) == 1
    assert events[0].type == "plan_created"
    assert events[0].plan is not None
    assert events[0].plan.title == "Ship v1"
    assert len(events[0].plan.steps) == 2


def test_claim_completes_previous_in_progress(store: PlanStore) -> None:
    events, emit = _capture_emitter()
    dispatch_update_plan(
        {
            "action": "create",
            "title": "x",
            "summary": "",
            "steps": [{"title": "a"}, {"title": "b"}],
        },
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    events.clear()
    dispatch_update_plan(
        {"action": "claim", "step_index": 0},
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    assert events[0].step.status == "in_progress"
    events.clear()
    dispatch_update_plan(
        {"action": "claim", "step_index": 1},
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    plan = store.get_active_for_session("s1")
    by_index = {s.index: s.status for s in plan.steps}
    assert by_index[0] == "completed"
    assert by_index[1] == "in_progress"


def test_complete_emits_step_update_then_plan_completes(store: PlanStore) -> None:
    events, emit = _capture_emitter()
    dispatch_update_plan(
        {
            "action": "create",
            "title": "x",
            "summary": "",
            "steps": [{"title": "a"}],
        },
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    events.clear()
    dispatch_update_plan(
        {"action": "complete", "step_index": 0, "note": "ok"},
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    assert any(e.type == "plan_step_completed" for e in events)
    plan = store.get_active_for_session("s1")
    assert plan is None  # all done → moved to completed


def test_block_then_unblock(store: PlanStore) -> None:
    events, emit = _capture_emitter()
    dispatch_update_plan(
        {"action": "create", "title": "t", "summary": "", "steps": [{"title": "a"}]},
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    events.clear()
    dispatch_update_plan(
        {"action": "block", "step_index": 0, "note": "need api key"},
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    assert events[0].step.status == "blocked"
    assert events[0].step.note == "need api key"
    events.clear()
    dispatch_update_plan(
        {"action": "unblock", "step_index": 0},
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    assert events[0].step.status == "pending"


def test_create_without_active_session_errors(store: PlanStore) -> None:
    with pytest.raises(ValueError):
        dispatch_update_plan(
            {"action": "claim", "step_index": 0},
            session_id="missing",
            plan_store=store,
        )


def test_step_index_out_of_range_errors(store: PlanStore) -> None:
    events, emit = _capture_emitter()
    dispatch_update_plan(
        {"action": "create", "title": "t", "summary": "", "steps": [{"title": "a"}]},
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    with pytest.raises(ValueError):
        dispatch_update_plan(
            {"action": "complete", "step_index": 5},
            session_id="s1",
            plan_store=store,
        )


def test_create_without_title_errors(store: PlanStore) -> None:
    with pytest.raises(ValueError):
        dispatch_update_plan(
            {"action": "create", "title": "", "summary": "", "steps": [{"title": "a"}]},
            session_id="s1",
            plan_store=store,
        )


def test_create_with_empty_steps_errors(store: PlanStore) -> None:
    with pytest.raises(ValueError):
        dispatch_update_plan(
            {"action": "create", "title": "t", "summary": "", "steps": []},
            session_id="s1",
            plan_store=store,
        )


def test_json_string_arguments(store: PlanStore) -> None:
    """Tool arguments can arrive as a JSON string from the model."""
    import json
    events, emit = _capture_emitter()
    raw = json.dumps({
        "action": "create",
        "title": "from-string",
        "summary": "",
        "steps": [{"title": "a"}],
    })
    dispatch_update_plan(
        raw,
        session_id="s1",
        plan_store=store,
        on_event=emit,
    )
    assert events[0].plan.title == "from-string"


def test_active_plan_as_prompt_block_renders(store: PlanStore) -> None:
    dispatch_update_plan(
        {
            "action": "create",
            "title": "Migrate DB",
            "summary": "from sqlite to pg",
            "steps": [
                {"title": "design schema", "acceptance": "schema.sql reviewed"},
                {"title": "write migration", "acceptance": "scripts pass"},
            ],
        },
        session_id="s1",
        plan_store=store,
    )
    plan = store.get_active_for_session("s1")
    block = active_plan_as_prompt_block(plan)
    assert "<active_plan>" in block
    assert "Migrate DB" in block
    assert "design schema" in block
    assert "[ ] pending" in block


def test_tool_schema_shape() -> None:
    """Schema includes the action enum and step list shape."""
    assert UPDATE_PLAN_TOOL["type"] == "function"
    fn = UPDATE_PLAN_TOOL["function"]
    assert fn["name"] == "update_plan"
    params = fn["parameters"]
    actions = params["properties"]["action"]["enum"]
    assert set(actions) == {"create", "claim", "complete", "block", "unblock", "cancel"}
    assert "steps" in params["properties"]


def _make_client(*, replies: list[str]) -> LLMClient:
    """Build a minimal LLMClient with FakeProvider for auto-detect tests."""
    provider = FakeProvider(responses=list(replies))
    return LLMClient(provider=provider)


def _make_config() -> LLMConfig:
    return LLMConfig(base_url="http://fake", api_key="fake", model="fake")


def test_should_auto_plan_returns_true_for_yes() -> None:
    client = _make_client(replies=["YES"])
    result = asyncio.run(
        should_auto_plan(client, _make_config(), "migrate the database to postgres")
    )
    assert result is True


def test_should_auto_plan_returns_false_for_no() -> None:
    client = _make_client(replies=["NO"])
    result = asyncio.run(
        should_auto_plan(client, _make_config(), "what is the weather today")
    )
    assert result is False


def test_should_auto_plan_handles_unexpected_response() -> None:
    client = _make_client(replies=["maybe"])
    result = asyncio.run(
        should_auto_plan(client, _make_config(), "do something")
    )
    assert result is False


def test_should_auto_plan_handles_yes_with_lowercase() -> None:
    client = _make_client(replies=["yes."])
    result = asyncio.run(
        should_auto_plan(client, _make_config(), "plan a trip")
    )
    assert result is True


def test_inject_plan_directive_adds_to_system_message() -> None:
    req = ChatRequest(
        config=LLMConfig(base_url="x", api_key="x", model="x"),
        messages=[
            ChatMessage(role="system", content="you are fae"),
            ChatMessage(role="user", content="hello"),
        ],
    )
    out = inject_plan_directive(req)
    sys_msg = out.messages[0]
    assert "update_plan" in sys_msg.content
    assert "you are fae" in sys_msg.content
    assert out.messages[1].role == "user"


def test_inject_plan_directive_is_idempotent() -> None:
    req = ChatRequest(
        config=LLMConfig(base_url="x", api_key="x", model="x"),
        messages=[ChatMessage(role="system", content="base")],
    )
    once = inject_plan_directive(req)
    twice = inject_plan_directive(once)
    assert once.messages[0].content == twice.messages[0].content


def test_inject_plan_directive_creates_system_message_if_missing() -> None:
    req = ChatRequest(
        config=LLMConfig(base_url="x", api_key="x", model="x"),
        messages=[ChatMessage(role="user", content="hi")],
    )
    out = inject_plan_directive(req)
    assert out.messages[0].role == "system"
    assert "update_plan" in out.messages[0].content