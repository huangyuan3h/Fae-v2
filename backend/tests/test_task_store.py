from __future__ import annotations

from pathlib import Path

import pytest

from fae.scheduler.tasks import (
    InvalidTaskTransition,
    TaskNotFound,
    TaskStatus,
    TaskStore,
    TASK_STATUSES,
    assert_transition,
    is_parked,
    is_terminal,
)


def _store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path / "tasks.db")


def test_allowed_transitions_match_design() -> None:
    assert TaskStatus.QUEUED.value in TASK_STATUSES
    assert TaskStatus.NEEDS_INPUT.value in TASK_STATUSES
    assert_transition("queued", "running")
    assert_transition("queued", "cancelled")
    assert_transition("running", "needs_input")
    assert_transition("running", "done")
    assert_transition("running", "failed")
    assert_transition("running", "cancelled")
    assert_transition("needs_input", "running")
    assert_transition("failed", "queued")
    assert_transition("cancelled", "queued")
    with pytest.raises(InvalidTaskTransition):
        assert_transition("done", "running")
    with pytest.raises(InvalidTaskTransition):
        assert_transition("queued", "done")
    with pytest.raises(InvalidTaskTransition):
        assert_transition("needs_input", "done")
    with pytest.raises(InvalidTaskTransition):
        assert_transition("cancelled", "running")
    assert is_terminal("done")
    assert not is_terminal("failed")
    assert is_parked("failed")
    assert is_parked("cancelled")
    assert not is_parked("done")


def test_create_defaults_to_queued(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.create_task(
        kind="research",
        title="Look up last week earnings",
        payload={"topic": "earnings"},
        session_id="s1",
        channel="http",
        max_attempts=3,
    )
    assert task.status == "queued"
    assert task.attempts == 0
    assert task.max_attempts == 3
    assert task.payload == {"topic": "earnings"}
    assert task.created_at == task.updated_at
    assert task.started_at is None
    assert task.finished_at is None
    assert not task.is_terminal
    assert not task.is_parked


def test_full_lifecycle_running_done(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.create_task(
        kind="schedule_daily", title="daily check-in", session_id="s"
    )
    after = store.claim(task.id)
    assert after.status == "running"
    assert after.attempts == 1
    assert after.started_at is not None
    finished = store.complete(after.id, result={"ok": True})
    assert finished.status == "done"
    assert finished.result_summary == {"ok": True}
    assert finished.finished_at is not None
    assert finished.is_terminal


def test_needs_input_then_running_then_done(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.create_task(kind="research", title="ask user", session_id="s")
    task = store.claim(task.id)
    task = store.request_input(
        task.id, prompt="需要城市", resume_token={"city_known": False}
    )
    assert task.status == "needs_input"
    assert task.resume_token["prompt"] == "需要城市"
    assert task.resume_token["context"] == {"city_known": False}
    task = store.provide_input(task.id, input_payload={"city": "Shanghai"})
    assert task.status == "running"
    assert task.resume_token["input"] == {"city": "Shanghai"}
    task = store.complete(task.id, result={"answer": 42})
    assert task.status == "done"


def test_fail_retry_then_completes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.create_task(kind="k", title="t", max_attempts=3)
    task = store.claim(task.id)
    failed = store.fail(
        task.id, error_code="timeout", error_message="30s cap"
    )
    assert failed.status == "failed"
    assert failed.error_code == "timeout"
    assert failed.is_parked
    requeued = store.retry(failed.id, note="retry from operator")
    assert requeued.status == "queued"
    assert requeued.attempts == 1
    # Retry of an unknown id raises TaskNotFound (not InvalidTaskTransition).
    with pytest.raises(TaskNotFound):
        store.retry("not-a-real-task")
    running = store.claim(requeued.id)
    assert running.attempts == 2
    done = store.complete(running.id, result={"ok": True})
    assert done.status == "done"


def test_cancel_idempotent_for_terminal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.create_task(kind="k", title="t")
    cancelled = store.cancel(task.id, note="user aborted")
    assert cancelled.status == "cancelled"
    again = store.cancel(cancelled.id)
    assert again.status == "cancelled"
    # Retry from cancelled succeeds.
    refreshed = store.retry(cancelled.id)
    assert refreshed.status == "queued"


def test_persists_after_restart(tmp_path: Path) -> None:
    db = tmp_path / "tasks.db"
    first = TaskStore(db)
    task = first.create_task(
        kind="k",
        title="t",
        payload={"foo": "bar"},
        session_id="alpha",
    )
    first.claim(task.id)
    first.request_input(
        task.id, prompt="待确认", resume_token={"k": 1}
    )
    first.close()

    second = TaskStore(db)
    loaded = second.get_task(task.id)
    assert loaded is not None
    assert loaded.status == "needs_input"
    assert loaded.payload == {"foo": "bar"}
    assert loaded.session_id == "alpha"
    assert loaded.resume_token["prompt"] == "待确认"
    # Repair cycle still works after restart.
    refreshed = second.provide_input(loaded.id, input_payload={"ack": True})
    assert refreshed.status == "running"


def test_recover_orphaned_running_moves_to_needs_input(tmp_path: Path) -> None:
    store = _store(tmp_path)
    short = store.create_task(kind="short", title="t")
    long_running = store.create_task(kind="long", title="t")
    store.claim(short.id)
    store.complete(short.id, result={"ok": True})
    store.claim(long_running.id)
    recovered = store.recover_orphaned_running(
        into="needs_input", reason="service_restart"
    )
    assert [t.id for t in recovered] == [long_running.id]
    loaded = store.get_task(long_running.id)
    assert loaded is not None
    assert loaded.status == "needs_input"
    assert loaded.result_summary["resume_reason"] == "service_restart"
    assert "resumed_at" in loaded.result_summary
    # claim bumped attempts to 1; recovery bumps it again (operator can resume).
    assert loaded.attempts == 2
    after = store.provide_input(long_running.id, input_payload={"resume": True})
    assert after.status == "running"


def test_recovery_rejects_disallowed_target(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.recover_orphaned_running(into="queued")
    with pytest.raises(ValueError):
        store.recover_orphaned_running(into="bogus")


def test_list_tasks_with_filters_and_pagination(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = []
    for i in range(5):
        created.append(
            store.create_task(
                kind=f"k{i % 2}",
                title=f"task {i}",
                session_id="alpha" if i % 2 == 0 else "beta",
            )
        )
    store.claim(created[0].id)
    only_running = store.list_tasks(status="running")
    assert {t.id for t in only_running} == {created[0].id}
    only_alpha = store.list_tasks(session_id="alpha")
    assert len(only_alpha) == 3
    paged = store.list_tasks(limit=2)
    assert len(paged) == 2
    earlier = store.list_tasks(before=created[-1].updated_at, limit=10)
    assert all(t.updated_at < created[-1].updated_at for t in earlier)


def test_status_counts_include_zero_buckets(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.create_task(kind="k", title="t", session_id="group")
    store.claim(task.id)
    counts = store.status_counts(session_id="group")
    assert counts["running"] == 1
    assert counts["queued"] == 0
    assert counts["done"] == 0
    assert set(counts) == set(TASK_STATUSES)


def test_payload_is_sanitized(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.create_task(
        kind="k",
        title="t",
        payload={
            "api_key": "sk-live",
            "nested": {"Authorization": "Bearer abc"},
            "ok": "public token=ok",
        },
    )
    loaded = store.get_task(task.id)
    assert loaded is not None
    assert loaded.payload["api_key"] == "[REDACTED]"
    assert loaded.payload["nested"]["Authorization"] == "[REDACTED]"
    # safe_text keeps length cap; rough sanity that result round-trips through JSON.


def test_max_attempts_must_be_positive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.create_task(kind="k", title="t", max_attempts=0)


def test_get_missing_task_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get_task("nope") is None
