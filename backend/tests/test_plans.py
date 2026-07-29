"""Tests for the Plan / plan-step persistence layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.plans import (
    InvalidPlanTransition,
    Plan,
    PlanStatus,
    PlanStep,
    PlanStepStatus,
    PlanStore,
)


@pytest.fixture()
def store(tmp_path: Path) -> PlanStore:
    s = PlanStore(tmp_path / "plans.db")
    yield s
    s.close()


def _make_steps(*titles: str) -> list[dict[str, str]]:
    return [{"title": t, "acceptance": f"verify {t}"} for t in titles]


def test_create_plan_makes_all_steps_pending(store: PlanStore) -> None:
    plan = store.create_plan(
        session_id="s1",
        title="Deploy app",
        summary="release v1",
        steps=_make_steps("build", "test", "push"),
    )
    assert plan.status == PlanStatus.ACTIVE.value
    assert len(plan.steps) == 3
    assert all(s.status == PlanStepStatus.PENDING.value for s in plan.steps)
    assert plan.steps[0].title == "build"
    assert plan.steps[0].index == 0
    assert plan.steps[0].started_at is None


def test_get_active_for_session_returns_latest_active(store: PlanStore) -> None:
    store.create_plan(
        session_id="s1", title="first", summary="",
        steps=_make_steps("a"),
    )
    p2 = store.create_plan(
        session_id="s1", title="second", summary="",
        steps=_make_steps("a"),
    )
    fetched = store.get_active_for_session("s1")
    assert fetched is not None
    assert fetched.id == p2.id
    assert fetched.title == "second"


def test_creating_new_plan_abandons_old_for_same_session(store: PlanStore) -> None:
    p1 = store.create_plan(
        session_id="s1", title="first", summary="",
        steps=_make_steps("a", "b"),
    )
    store.create_plan(
        session_id="s1", title="second", summary="",
        steps=_make_steps("x"),
    )
    abandoned = store.get_plan(p1.id)
    assert abandoned is not None
    assert abandoned.status == PlanStatus.ABANDONED.value
    assert abandoned.finished_at is not None


def test_claim_then_complete_step(store: PlanStore) -> None:
    plan = store.create_plan(
        session_id="s1", title="t", summary="",
        steps=_make_steps("a", "b"),
    )
    store.claim_step(plan.steps[0].id)
    updated = store.complete_step(plan.steps[0].id, note="done")
    assert updated.status == PlanStepStatus.COMPLETED.value
    assert updated.started_at is not None
    assert updated.finished_at is not None
    assert updated.note == "done"


def test_claiming_a_step_auto_computes_previous_in_progress(store: PlanStore) -> None:
    plan = store.create_plan(
        session_id="s1", title="t", summary="",
        steps=_make_steps("a", "b"),
    )
    store.claim_step(plan.steps[0].id)
    store.claim_step(plan.steps[1].id)
    after = store.get_plan(plan.id)
    assert after is not None
    by_status = {s.index: s.status for s in after.steps}
    assert by_status[0] == PlanStepStatus.COMPLETED.value
    assert by_status[1] == PlanStepStatus.IN_PROGRESS.value


def test_completing_all_steps_marks_plan_completed(store: PlanStore) -> None:
    plan = store.create_plan(
        session_id="s1", title="t", summary="",
        steps=_make_steps("a", "b"),
    )
    store.claim_step(plan.steps[0].id)
    store.complete_step(plan.steps[0].id)
    store.claim_step(plan.steps[1].id)
    store.complete_step(plan.steps[1].id)
    after = store.get_plan(plan.id)
    assert after is not None
    assert after.status == PlanStatus.COMPLETED.value
    assert after.finished_at is not None


def test_blocking_pending_step_then_unblock(store: PlanStore) -> None:
    plan = store.create_plan(
        session_id="s1", title="t", summary="",
        steps=_make_steps("a"),
    )
    blocked = store.block_step(plan.steps[0].id, reason="need api key")
    assert blocked.status == PlanStepStatus.BLOCKED.value
    assert blocked.note == "need api key"
    pending = store.unblock_step(plan.steps[0].id)
    assert pending.status == PlanStepStatus.PENDING.value


def test_invalid_transition_raises(store: PlanStore) -> None:
    plan = store.create_plan(
        session_id="s1", title="t", summary="",
        steps=_make_steps("a"),
    )
    store.complete_step(plan.steps[0].id)
    with pytest.raises(InvalidPlanTransition):
        store.complete_step(plan.steps[0].id)


def test_clear_session(store: PlanStore) -> None:
    store.create_plan(session_id="s1", title="a", summary="", steps=_make_steps("x"))
    store.create_plan(session_id="s1", title="b", summary="", steps=_make_steps("y"))
    store.create_plan(session_id="s2", title="c", summary="", steps=_make_steps("z"))
    deleted = store.clear("s1")
    assert deleted == 2
    assert store.get_active_for_session("s1") is None
    assert store.get_active_for_session("s2") is not None


def test_clear_global(store: PlanStore) -> None:
    store.create_plan(session_id="s1", title="a", summary="", steps=_make_steps("x"))
    store.create_plan(session_id="s2", title="b", summary="", steps=_make_steps("y"))
    deleted = store.clear(None)
    assert deleted == 2
    assert store.get_active_for_session("s1") is None
    assert store.get_active_for_session("s2") is None


def test_to_dict_round_trip(store: PlanStore) -> None:
    plan = store.create_plan(
        session_id="s1", title="Roundtrip", summary="demo",
        steps=_make_steps("a", "b", "c"),
    )
    store.claim_step(plan.steps[0].id)
    store.complete_step(plan.steps[0].id)
    fresh = store.get_plan(plan.id)
    serialized = store.to_dict(fresh)
    assert serialized["title"] == "Roundtrip"
    assert serialized["status"] == PlanStatus.ACTIVE.value
    assert len(serialized["steps"]) == 3
    assert serialized["steps"][0]["status"] == PlanStepStatus.COMPLETED.value