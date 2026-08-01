"""Tests for long-task idempotency, CAS state transitions, progress
and structured error history (P1 follow-up).
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from fae.scheduler.tasks import (
    AttemptsExhausted,
    IdempotencyConflict,
    InvalidTaskTransition,
    TaskNotFound,
    TaskStore,
    TaskStatus,
)


@pytest.fixture()
def store(tmp_path: Path) -> TaskStore:
    s = TaskStore(tmp_path / "tasks.db")
    yield s
    s.close()


# ── Idempotency ──────────────────────────────────────────────────────


def test_create_idempotency_key_replays_same_task(store: TaskStore) -> None:
    fp = "fp-abc"
    first = store.create_task(
        kind="research",
        title="Look up X",
        payload={"q": "X"},
        session_id="s1",
        idempotency_key="K1",
        fingerprint=fp,
    )
    second = store.create_task(
        kind="research",
        title="Look up X",
        payload={"q": "X"},
        session_id="s1",
        idempotency_key="K1",
        fingerprint=fp,
    )
    assert second.id == first.id
    assert second.idempotency_key == "K1"
    assert second.fingerprint == fp

    rows = store._conn.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE idempotency_key = 'K1'"
    ).fetchone()["n"]
    assert rows == 1


def test_create_idempotency_key_with_different_payload_raises(store: TaskStore) -> None:
    store.create_task(
        kind="research",
        title="Look up X",
        payload={"q": "X"},
        session_id="s1",
        idempotency_key="K1",
        fingerprint="fp-abc",
    )
    with pytest.raises(IdempotencyConflict) as excinfo:
        store.create_task(
            kind="research",
            title="Look up X",
            payload={"q": "Y"},  # different payload
            session_id="s1",
            idempotency_key="K1",
            fingerprint="fp-xyz",
        )
    assert excinfo.value.task_id
    assert excinfo.value.key == "K1"


def test_create_without_idempotency_key_always_inserts(store: TaskStore) -> None:
    a = store.create_task(kind="research", title="t", payload={}, session_id="s1")
    b = store.create_task(kind="research", title="t", payload={}, session_id="s1")
    assert a.id != b.id


# ── CAS claim / complete / fail ─────────────────────────────────────


def test_concurrent_claim_only_one_wins(tmp_path: Path) -> None:
    """Two threads attempt claim; only one succeeds."""
    store_a = TaskStore(tmp_path / "a.db")
    store_b = TaskStore(tmp_path / "b.db")
    try:
        # Both TaskStore instances point at the same underlying SQLite file
        # so we can simulate multi-process / multi-thread contention.
        store_b._conn.close()
        store_b._conn = store_a._conn
    except Exception:
        pass
    # Easier: test serial duplicate claim using two TaskStore handles on
    # the same file (open two connections to the same DB).
    store_a.close()
    store_b.close()

    store_a = TaskStore(tmp_path / "a.db")
    store_b = TaskStore(tmp_path / "a.db")  # same file
    try:
        task = store_a.create_task(kind="k", title="t", session_id="s1")
        tid = task.id

        results: list[Exception | None] = [None, None]

        def claim() -> None:
            try:
                store_b.claim(tid)
                results[0] = None
            except InvalidTaskTransition:
                results[0] = InvalidTaskTransition("running", "running")

        def claim2() -> None:
            try:
                store_a.claim(tid)
                results[1] = None
            except (InvalidTaskTransition, AttemptsExhausted) as exc:
                results[1] = exc

        t1 = threading.Thread(target=claim)
        t2 = threading.Thread(target=claim2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one of the two threads must have raised.
        assert (results[0] is None) != (results[1] is None)
        final = store_a.get_task_or_raise(tid)
        assert final.status == TaskStatus.RUNNING.value
        assert final.attempts == 1
    finally:
        store_a.close()
        store_b.close()


def test_claim_enforces_max_attempts(store: TaskStore) -> None:
    task = store.create_task(
        kind="k", title="t", session_id="s1", max_attempts=2
    )
    store.claim(task.id)  # attempts=1
    store.fail(task.id, error_code="x")
    store.retry(task.id)   # back to queued, attempts still 1
    store.claim(task.id)  # attempts=2
    store.fail(task.id, error_code="y")
    store.retry(task.id)   # back to queued, attempts still 2
    with pytest.raises(AttemptsExhausted) as excinfo:
        store.claim(task.id)
    assert excinfo.value.attempts == 2
    assert excinfo.value.max_attempts == 2


def test_duplicate_claim_is_rejected(store: TaskStore) -> None:
    task = store.create_task(kind="k", title="t", session_id="s1")
    store.claim(task.id)
    with pytest.raises(InvalidTaskTransition):
        store.claim(task.id)
    final = store.get_task_or_raise(task.id)
    assert final.attempts == 1


def test_duplicate_complete_is_idempotent_with_same_result(store: TaskStore) -> None:
    task = store.create_task(kind="k", title="t", session_id="s1")
    store.claim(task.id)
    store.complete(task.id, result={"v": 1})
    # Same result → replay.
    again = store.complete(task.id, result={"v": 1})
    assert again.result_summary == {"v": 1}
    # Different result → conflict.
    with pytest.raises(InvalidTaskTransition):
        store.complete(task.id, result={"v": 2})


def test_duplicate_complete_on_running_rejected(store: TaskStore) -> None:
    task = store.create_task(kind="k", title="t", session_id="s1")
    store.claim(task.id)
    store.complete(task.id, result={"v": 1})
    final = store.get_task_or_raise(task.id)
    assert final.status == "done"
    # Cannot complete again with different result.
    with pytest.raises(InvalidTaskTransition):
        store.complete(task.id, result={"v": 2})


def test_duplicate_fail_rejected(store: TaskStore) -> None:
    task = store.create_task(kind="k", title="t", session_id="s1")
    store.claim(task.id)
    store.fail(task.id, error_code="e1", error_message="boom")
    with pytest.raises(InvalidTaskTransition):
        store.fail(task.id, error_code="e2", error_message="boom2")
    final = store.get_task_or_raise(task.id)
    assert final.error_code == "e1"


# ── Retry clears stale state ────────────────────────────────────────


def test_retry_clears_stale_state(store: TaskStore) -> None:
    task = store.create_task(kind="k", title="t", session_id="s1", max_attempts=3)
    store.claim(task.id)
    store.fail(task.id, error_code="oops", error_message="bad network")

    refreshed = store.get_task_or_raise(task.id)
    assert refreshed.status == "failed"
    assert refreshed.error_code == "oops"
    assert refreshed.started_at is not None
    assert refreshed.finished_at is not None

    store.retry(task.id)
    refreshed = store.get_task_or_raise(task.id)
    assert refreshed.status == "queued"
    assert refreshed.error_code is None
    assert refreshed.error_message is None
    assert refreshed.started_at is None
    assert refreshed.finished_at is None
    # attempt count NOT incremented by retry (only claim does that).
    assert refreshed.attempts == 1

    # History is preserved in notes.
    history = store.error_history(task.id)
    assert any(h.get("event") == "attempt_failed" for h in history)


# ── Progress visibility ────────────────────────────────────────────


def test_progress_round_trip(store: TaskStore) -> None:
    task = store.create_task(kind="k", title="t", session_id="s1")
    store.claim(task.id)
    store.update_progress(
        task.id,
        progress={"current": 1, "total": 5, "percent": 20, "current_step": "fetch"},
    )
    refreshed = store.get_task_or_raise(task.id)
    assert refreshed.progress["current"] == 1
    assert refreshed.progress["percent"] == 20
    assert refreshed.progress["current_step"] == "fetch"

    store.update_progress(task.id, progress={"current_step": "parse", "percent": 40})
    refreshed = store.get_task_or_raise(task.id)
    # Merged, not replaced.
    assert refreshed.progress["current"] == 1
    assert refreshed.progress["current_step"] == "parse"
    assert refreshed.progress["percent"] == 40


def test_progress_rejected_after_done(store: TaskStore) -> None:
    task = store.create_task(kind="k", title="t", session_id="s1")
    store.claim(task.id)
    store.update_progress(task.id, progress={"x": 1})
    store.complete(task.id, result={"v": 1})
    # Same progress on done is idempotent.
    again = store.update_progress(task.id, progress={"x": 1})
    assert again.progress == {"x": 1}
    with pytest.raises(InvalidTaskTransition):
        store.update_progress(task.id, progress={"y": 2})


# ── Error history ──────────────────────────────────────────────────


def test_fail_appends_structured_attempt_failed(store: TaskStore) -> None:
    task = store.create_task(kind="k", title="t", session_id="s1", max_attempts=3)
    store.claim(task.id)
    store.fail(task.id, error_code="telegram_timeout", error_message="send timed out")
    history = store.error_history(task.id)
    assert len(history) == 1
    entry = history[0]
    assert entry["event"] == "attempt_failed"
    assert entry["error_code"] == "telegram_timeout"
    assert entry["error_message"] == "send timed out"
    assert entry["attempt"] == 1

    # Second attempt fails → both events recorded.
    store.retry(task.id)
    store.claim(task.id)
    store.fail(task.id, error_code="telegram_4xx", error_message="chat not found")
    history = store.error_history(task.id)
    assert len(history) == 2
    assert history[1]["attempt"] == 2
    assert history[1]["error_code"] == "telegram_4xx"


# ── Recovery respects idempotency semantics ─────────────────────────


def test_recovery_does_not_invalidate_idempotency_keys(store: TaskStore) -> None:
    task = store.create_task(
        kind="k",
        title="t",
        session_id="s1",
        idempotency_key="K-X",
        fingerprint="fp-x",
    )
    store.claim(task.id)  # running
    store.recover_orphaned_running()  # → needs_input

    # Idempotent replay still returns the same row.
    replay = store.create_task(
        kind="k",
        title="t",
        session_id="s1",
        idempotency_key="K-X",
        fingerprint="fp-x",
    )
    assert replay.id == task.id
    assert replay.status == "needs_input"