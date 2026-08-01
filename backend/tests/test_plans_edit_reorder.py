"""Tests for Plan Mode · 手动编辑与重排序 (P1 follow-up).

Covers:
- ``PlanStore.edit_step``: title / acceptance update, terminal-step
  rejection, no-op semantics on terminal status, persistence + reload.
- ``PlanStore.reorder_step``: swap-based idx reordering, terminal-step
  rejection, range checks, no-op on same index, note preservation.
- HTTP layer: PATCH ``/api/plans/{plan_id}/steps/{step_id}`` and POST
  ``/api/plans/{plan_id}/reorder`` against the active plan, with
  error mapping (400/404/409).
- Cross-layer: after edit + reorder the next ``get_active_for_session``
  reflects new title / idx, and ``active_plan_as_prompt_block`` picks
  up the new fields — i.e. the LLM view stays consistent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae.agent.plan_tools import active_plan_as_prompt_block, dispatch_update_plan
from fae.api import create_app
from fae.config import Settings
from fae.plans import InvalidPlanTransition, PlanStore


@pytest.fixture()
def store(tmp_path: Path) -> PlanStore:
    s = PlanStore(tmp_path / "plans.db")
    yield s
    s.close()


def _create_three_step_plan(store: PlanStore, session_id: str = "s1") -> None:
    dispatch_update_plan(
        {
            "action": "create",
            "title": "ship",
            "summary": "release",
            "steps": [
                {"title": "build", "acceptance": "compiles"},
                {"title": "test", "acceptance": "pytest passes"},
                {"title": "deploy", "acceptance": "live"},
            ],
        },
        session_id=session_id,
        plan_store=store,
    )


# ── edit_step ─────────────────────────────────────────────────────────


def test_edit_step_updates_title_and_acceptance(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    target = plan.steps[0]

    updated = store.edit_step(target.id, title="build (v2)", acceptance="compiles + lints")
    assert updated.title == "build (v2)"
    assert updated.acceptance == "compiles + lints"
    assert updated.status == "pending"

    refreshed = store.get_active_for_session("s1")
    assert refreshed.steps[0].title == "build (v2)"
    assert refreshed.steps[0].acceptance == "compiles + lints"


def test_edit_step_partial_title_only(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    target = plan.steps[0]
    original_acc = target.acceptance

    updated = store.edit_step(target.id, title="renamed")
    assert updated.title == "renamed"
    assert updated.acceptance == original_acc


def test_edit_step_partial_acceptance_only(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    target = plan.steps[0]
    original_title = target.title

    updated = store.edit_step(target.id, acceptance="new criteria")
    assert updated.acceptance == "new criteria"
    assert updated.title == original_title


def test_edit_step_empty_string_clears_field(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    target = plan.steps[0]

    updated = store.edit_step(target.id, acceptance="")
    assert updated.acceptance == ""


def test_edit_step_no_fields_raises(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    target = plan.steps[0]
    with pytest.raises(ValueError):
        store.edit_step(target.id)


def test_edit_step_rejects_completed(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    target = plan.steps[0]
    store.claim_step(target.id)
    store.complete_step(target.id)

    with pytest.raises(InvalidPlanTransition):
        store.edit_step(target.id, title="too late")


def test_edit_step_rejects_cancelled(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    target = plan.steps[1]
    store.cancel_step(target.id)

    with pytest.raises(InvalidPlanTransition):
        store.edit_step(target.id, acceptance="anything")


def test_edit_step_unknown_step_raises(store: PlanStore) -> None:
    _create_three_step_plan(store)
    with pytest.raises(LookupError):
        store.edit_step("missing-step-id", title="x")


def test_edit_step_preserves_idx_and_note(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    target = plan.steps[0]
    original_idx = target.index
    store.append_step_note(target.id, "user: please also lint")

    updated = store.edit_step(target.id, title="renamed")
    assert updated.index == original_idx
    assert "lint" in updated.note


def test_edit_step_during_blocked_is_allowed(store: PlanStore) -> None:
    """Blocked steps should be editable — that's the user's reengage path."""
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    target = plan.steps[0]
    store.block_step(target.id, reason="need api key")

    updated = store.edit_step(target.id, acceptance="supply key via header")
    assert updated.status == "blocked"
    assert updated.acceptance == "supply key via header"


# ── reorder_step ─────────────────────────────────────────────────────


def test_reorder_step_swap_two_adjacent(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    s0, s1, s2 = plan.steps
    assert [s.title for s in plan.steps] == ["build", "test", "deploy"]

    store.reorder_step(s0.id, 1)  # build → index 1
    refreshed = store.get_active_for_session("s1")
    by_index = {s.index: s.title for s in refreshed.steps}
    assert by_index == {0: "test", 1: "build", 2: "deploy"}


def test_reorder_step_move_to_end(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    s0 = plan.steps[0]
    store.reorder_step(s0.id, 2)
    refreshed = store.get_active_for_session("s1")
    by_index = {s.index: s.title for s in refreshed.steps}
    assert by_index == {0: "test", 1: "deploy", 2: "build"}


def test_reorder_step_move_to_front(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    s2 = plan.steps[2]
    store.reorder_step(s2.id, 0)
    refreshed = store.get_active_for_session("s1")
    by_index = {s.index: s.title for s in refreshed.steps}
    assert by_index == {0: "deploy", 1: "build", 2: "test"}


def test_reorder_step_same_index_is_noop(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    s1 = plan.steps[1]
    store.reorder_step(s1.id, 1)
    refreshed = store.get_active_for_session("s1")
    assert [s.title for s in refreshed.steps] == ["build", "test", "deploy"]


def test_reorder_step_out_of_range_raises(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    s0 = plan.steps[0]
    with pytest.raises(ValueError):
        store.reorder_step(s0.id, 99)
    with pytest.raises(ValueError):
        store.reorder_step(s0.id, -1)


def test_reorder_step_rejects_completed(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    s0 = plan.steps[0]
    store.claim_step(s0.id)
    store.complete_step(s0.id)
    with pytest.raises(InvalidPlanTransition):
        store.reorder_step(s0.id, 2)


def test_reorder_step_rejects_cancelled(store: PlanStore) -> None:
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    s2 = plan.steps[2]
    store.cancel_step(s2.id)
    with pytest.raises(InvalidPlanTransition):
        store.reorder_step(s2.id, 0)


def test_reorder_step_preserves_note(store: PlanStore) -> None:
    """Acceptance criterion: note persists across reorder."""
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    s0 = plan.steps[0]
    store.append_step_note(s0.id, "user: must ship to staging first")

    store.reorder_step(s0.id, 2)
    refreshed = store.get_active_for_session("s1")
    moved = next(s for s in refreshed.steps if s.id == s0.id)
    assert moved.index == 2
    assert "staging" in moved.note


def test_reorder_step_unknown_step_raises(store: PlanStore) -> None:
    _create_three_step_plan(store)
    with pytest.raises(LookupError):
        store.reorder_step("missing-step-id", 0)


# ── LLM view consistency ────────────────────────────────────────────


def test_active_plan_block_reflects_edit_and_reorder(store: PlanStore) -> None:
    """Acceptance criterion: LLM next turn sees edited + reordered plan."""
    _create_three_step_plan(store)
    plan = store.get_active_for_session("s1")
    s0 = plan.steps[0]

    store.edit_step(s0.id, title="build (typed-checked)", acceptance="compiles + mypy")
    store.reorder_step(s0.id, 2)

    refreshed = store.get_active_for_session("s1")
    block = active_plan_as_prompt_block(refreshed)
    assert "build (typed-checked)" in block
    assert "compiles + mypy" in block
    # Step with new index 2 should still appear with its new idx in the block.
    assert "2. [ ] pending: build (typed-checked)" in block


# ── HTTP layer ────────────────────────────────────────────────────────


def _build_client(tmp_path) -> TestClient:
    settings = Settings(
        letta_mode="off",
        scheduler_enabled=False,
        tool_audit_db_path=str(tmp_path / "audit.db"),
        agent_trace_db_path=str(tmp_path / "trace.db"),
        plans_db_path=str(tmp_path / "plans.db"),
    )
    app = create_app(settings=settings)
    return TestClient(app)


def test_http_edit_step_returns_updated_plan(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        store = client.app.state.plan_store
        _create_three_step_plan(store)
        plan = store.get_active_for_session("s1")
        sid = plan.steps[0].id
        pid = plan.id

        resp = client.patch(
            f"/api/plans/{pid}/steps/{sid}",
            json={"title": "build (v2)"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        refreshed = next(s for s in data["plan"]["steps"] if s["id"] == sid)
        assert refreshed["title"] == "build (v2)"


def test_http_edit_step_rejects_completed(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        store = client.app.state.plan_store
        _create_three_step_plan(store)
        plan = store.get_active_for_session("s1")
        sid = plan.steps[0].id
        pid = plan.id
        # claim + complete
        store.claim_step(sid)
        store.complete_step(sid)

        resp = client.patch(
            f"/api/plans/{pid}/steps/{sid}",
            json={"title": "too late"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "step_terminal"


def test_http_edit_step_no_fields_400(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        store = client.app.state.plan_store
        _create_three_step_plan(store)
        plan = store.get_active_for_session("s1")
        sid = plan.steps[0].id
        pid = plan.id

        resp = client.patch(
            f"/api/plans/{pid}/steps/{sid}", json={}
        )
        assert resp.status_code == 400


def test_http_edit_step_unknown_plan_404(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        resp = client.patch(
            "/api/plans/nonexistent/steps/nonexistent",
            json={"title": "x"},
        )
        assert resp.status_code == 404


def test_http_edit_step_step_not_in_plan_404(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        store = client.app.state.plan_store
        _create_three_step_plan(store)
        plan = store.get_active_for_session("s1")
        pid = plan.id

        resp = client.patch(
            f"/api/plans/{pid}/steps/step-from-other-plan",
            json={"title": "x"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "step_not_in_plan"


def test_http_reorder_step_returns_updated_plan(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        store = client.app.state.plan_store
        _create_three_step_plan(store)
        plan = store.get_active_for_session("s1")
        s0 = plan.steps[0]
        pid = plan.id

        resp = client.post(
            f"/api/plans/{pid}/reorder",
            json={"step_id": s0.id, "new_index": 2},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        by_idx = {s["index"]: s["title"] for s in data["plan"]["steps"]}
        assert by_idx == {0: "test", 1: "deploy", 2: "build"}


def test_http_reorder_step_out_of_range_400(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        store = client.app.state.plan_store
        _create_three_step_plan(store)
        plan = store.get_active_for_session("s1")
        s0 = plan.steps[0]
        pid = plan.id

        resp = client.post(
            f"/api/plans/{pid}/reorder",
            json={"step_id": s0.id, "new_index": 99},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "out_of_range"


def test_http_reorder_step_rejects_terminal(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        store = client.app.state.plan_store
        _create_three_step_plan(store)
        plan = store.get_active_for_session("s1")
        s0 = plan.steps[0]
        pid = plan.id
        store.cancel_step(s0.id)

        resp = client.post(
            f"/api/plans/{pid}/reorder",
            json={"step_id": s0.id, "new_index": 1},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "step_terminal"


def test_http_reorder_step_unknown_plan_404(tmp_path) -> None:
    with _build_client(tmp_path) as client:
        resp = client.post(
            "/api/plans/nonexistent/reorder",
            json={"step_id": "x", "new_index": 0},
        )
        assert resp.status_code == 404


def test_http_edit_then_reorder_round_trip(tmp_path) -> None:
    """End-to-end: edit title, reorder, then verify via GET /active."""
    with _build_client(tmp_path) as client:
        store = client.app.state.plan_store
        _create_three_step_plan(store)
        plan = store.get_active_for_session("s1")
        s0 = plan.steps[0]
        pid = plan.id

        client.patch(
            f"/api/plans/{pid}/steps/{s0.id}",
            json={"title": "build (typed)", "acceptance": "compiles + lints"},
        )
        client.post(
            f"/api/plans/{pid}/reorder",
            json={"step_id": s0.id, "new_index": 2},
        )

        loaded = client.get("/api/plans/active", params={"session_id": "s1"}).json()
        moved = next(s for s in loaded["plan"]["steps"] if s["id"] == s0.id)
        assert moved["title"] == "build (typed)"
        assert moved["acceptance"] == "compiles + lints"
        assert moved["index"] == 2