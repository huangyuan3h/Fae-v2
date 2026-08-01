"""Persistent task state machine.

A long-lived unit of work that the agent commits to but cannot finish in a
single turn. Each task carries a small JSON ``payload`` plus a status that
moves through a documented transition graph.

States (``TaskStatus``):
  - ``queued``        — created, not yet picked up
  - ``running``       — worker is actively executing it
  - ``needs_input``   — paused waiting for human clarification / approval
  - ``done``          — terminal success (only reached from ``running``)
  - ``failed``        — terminal error (only reached from ``running`` /
                        ``needs_input``)
  - ``cancelled``     — terminal — operator / user aborted it

Allowed transitions:
    queued      → running | cancelled
    running     → needs_input | done | failed | cancelled
    needs_input → running | failed | cancelled
    failed      → queued   (operator retry, attempts += 1)
    cancelled   → queued   (operator retry, attempts += 1)
    done        → (terminal, no further transitions)

Persistence:
  - Single SQLite DB (WAL) for crash safety.
  - Recovery sweep on startup: orphaned ``running`` rows (no worker holding
    them after a restart) are rewritten to ``needs_input`` with reason
    ``service_restart`` so the user can resume instead of silently dropping
    work.
  - ``payload`` and ``result_summary`` go through ``safe_json`` to avoid
    leaking API keys / tokens into the store.

Idempotency & CAS (P1 follow-up):
  - ``create_task`` accepts ``idempotency_key`` + ``fingerprint``. A repeat
    call with the same key + matching fingerprint replays the original
    task; mismatched fingerprints surface ``IdempotencyConflict``.
  - ``claim`` / ``complete`` / ``fail`` use a SQLite ``BEGIN IMMEDIATE``
    + ``UPDATE ... WHERE status = ? AND attempts < max_attempts`` so a
    duplicate ``claim`` cannot succeed and a duplicate ``complete`` cannot
    overwrite an already-terminal task.
  - ``max_attempts`` is enforced: claim past the limit raises
    ``AttemptsExhausted`` rather than silently retrying forever.
  - ``retry`` uses a sentinel (``_UNSET``) to truly clear the previous
    error / result / resume_token / timestamps; attempts counter only
    increments on real claim.

Scope boundaries:
  - This module does not run jobs. It only persists status transitions
    so the rest of the system (HTTP, WS, Telegram, scheduler loop) can
    observe and resume.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from fae.sanitize import safe_json, safe_text

# Sentinel to distinguish "field not provided" from "explicitly cleared to NULL"
# in ``TaskUpdate``. Used by retry/clear paths to actually overwrite
# fields like ``error_code`` and ``started_at`` instead of leaving the
# previous value in place.
_UNSET: Any = object()


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


TASK_STATUSES: frozenset[str] = frozenset(s.value for s in TaskStatus)
TERMINAL_OR_PARKED: frozenset[str] = frozenset(
    {
        TaskStatus.DONE.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }
)


_ALLOWED: dict[str, frozenset[str]] = {
    TaskStatus.QUEUED.value: frozenset(
        {TaskStatus.RUNNING.value, TaskStatus.CANCELLED.value}
    ),
    TaskStatus.RUNNING.value: frozenset(
        {
            TaskStatus.NEEDS_INPUT.value,
            TaskStatus.DONE.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }
    ),
    TaskStatus.NEEDS_INPUT.value: frozenset(
        {
            TaskStatus.RUNNING.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }
    ),
    TaskStatus.FAILED.value: frozenset({TaskStatus.QUEUED.value}),
    TaskStatus.CANCELLED.value: frozenset({TaskStatus.QUEUED.value}),
    TaskStatus.DONE.value: frozenset(),
}


class InvalidTaskTransition(ValueError):
    """Raised when ``from`` → ``to`` is not a permitted edge."""

    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(
            f"invalid task transition: {from_status} -> {to_status}"
        )
        self.from_status = from_status
        self.to_status = to_status


class AttemptsExhausted(RuntimeError):
    """Raised when a ``claim`` would exceed ``max_attempts``."""

    def __init__(self, attempts: int, max_attempts: int) -> None:
        super().__init__(
            f"task attempts exhausted: {attempts}/{max_attempts}"
        )
        self.attempts = attempts
        self.max_attempts = max_attempts


class IdempotencyConflict(RuntimeError):
    """Raised when the same ``idempotency_key`` arrives with a different
    request fingerprint."""

    def __init__(self, task_id: str, key: str) -> None:
        super().__init__(
            f"idempotency key {key!r} already bound to a different payload (task {task_id})"
        )
        self.task_id = task_id
        self.key = key


class TaskNotFound(LookupError):
    """Raised when ``task_id`` does not exist."""


def assert_transition(from_status: str, to_status: str) -> None:
    if from_status not in TASK_STATUSES:
        raise ValueError(f"unknown source status: {from_status!r}")
    if to_status not in TASK_STATUSES:
        raise ValueError(f"unknown target status: {to_status!r}")
    if to_status not in _ALLOWED[from_status]:
        raise InvalidTaskTransition(from_status, to_status)


def is_terminal(status: str) -> bool:
    return status == TaskStatus.DONE.value


def is_parked(status: str) -> bool:
    """Terminal-but-retryable: failed or cancelled (but NOT done)."""
    return status in {TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}


@dataclass
class Task:
    id: str
    kind: str
    title: str
    payload: dict[str, Any]
    status: str
    parent_id: str | None
    session_id: str
    channel: str
    attempts: int
    max_attempts: int
    result_summary: dict[str, Any]
    error_code: str | None
    error_message: str | None
    resume_token: dict[str, Any]
    created_at: float
    updated_at: float
    started_at: float | None
    finished_at: float | None
    extra: dict[str, Any] = field(default_factory=dict)
    notes: list[dict[str, Any]] = field(default_factory=list)
    idempotency_key: str | None = None
    fingerprint: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return is_terminal(self.status)

    @property
    def is_parked(self) -> bool:
        return is_parked(self.status)


@dataclass
class TaskUpdate:
    """Patch payload for ``TaskStore.update_task``.

    ``resume_token`` and ``result`` are treated as JSON objects so they get
    sanitized by ``safe_json`` before persistence. ``error_*`` / ``result`` /
    ``resume_token`` accept a sentinel (``_UNSET``) to mean "explicitly
    clear this column to NULL" so retry paths can wipe stale state.
    """

    status: Any = None
    result: Any = None
    error_code: Any = None
    error_message: Any = None
    resume_token: Any = None
    session_id: str | None = None
    reset_started_at: bool = False
    clear_started_at: bool = False
    clear_finished_at: bool = False
    progress: dict[str, Any] | None = None
    note: str | None = None


def _decode_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _decode_notes(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


class TaskStore:
    """SQLite-backed task store (WAL)."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._closed = False
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=3000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    @property
    def closed(self) -> bool:
        return self._closed

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY,
                  kind TEXT NOT NULL,
                  title TEXT NOT NULL,
                  payload_json TEXT NOT NULL DEFAULT '{}',
                  status TEXT NOT NULL,
                  parent_id TEXT,
                  session_id TEXT NOT NULL DEFAULT 'default',
                  channel TEXT NOT NULL DEFAULT 'unknown',
                  attempts INTEGER NOT NULL DEFAULT 1,
                  max_attempts INTEGER NOT NULL DEFAULT 1,
                  result_json TEXT NOT NULL DEFAULT '{}',
                  error_code TEXT,
                  error_message TEXT,
                  resume_token_json TEXT,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  started_at REAL,
                  finished_at REAL,
                  extra_json TEXT NOT NULL DEFAULT '{}',
                  notes_json TEXT NOT NULL DEFAULT '[]',
                  idempotency_key TEXT,
                  fingerprint TEXT,
                  progress_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status_updated
                  ON tasks (status, updated_at, id);
                CREATE INDEX IF NOT EXISTS idx_tasks_session_updated
                  ON tasks (session_id, updated_at, id);
                CREATE INDEX IF NOT EXISTS idx_tasks_kind_updated
                  ON tasks (kind, updated_at, id);
                """
            )
            self._migrate_schema()
            self._conn.commit()

    def _migrate_schema(self) -> None:
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(tasks)")
        }
        if "notes_json" not in cols:
            self._conn.execute(
                "ALTER TABLE tasks "
                "ADD COLUMN notes_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "idempotency_key" not in cols:
            self._conn.execute(
                "ALTER TABLE tasks "
                "ADD COLUMN idempotency_key TEXT"
            )
        if "fingerprint" not in cols:
            self._conn.execute(
                "ALTER TABLE tasks "
                "ADD COLUMN fingerprint TEXT"
            )
        if "progress_json" not in cols:
            self._conn.execute(
                "ALTER TABLE tasks "
                "ADD COLUMN progress_json TEXT NOT NULL DEFAULT '{}'"
            )
        # Re-check after ALTER and create the UNIQUE partial index now
        # that the column is guaranteed to exist.
        self._conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_session_idem
              ON tasks (session_id, idempotency_key)
              WHERE idempotency_key IS NOT NULL
            """
        )

    # ── Creation ──────────────────────────────────────────────────────

    def create_task(
        self,
        *,
        kind: str,
        title: str,
        payload: Mapping[str, Any] | None = None,
        session_id: str = "default",
        channel: str = "unknown",
        parent_id: str | None = None,
        max_attempts: int = 1,
        extra: Mapping[str, Any] | None = None,
        task_id: str | None = None,
        idempotency_key: str | None = None,
        fingerprint: str | None = None,
    ) -> Task:
        """Create or replay a task.

        Idempotent when ``idempotency_key`` is provided:

        - same key + matching fingerprint → returns the existing row
        - same key + different fingerprint → raises ``IdempotencyConflict``
        - no key → always inserts (legacy behaviour)
        """
        safe_kind = safe_text(kind)
        if not safe_kind:
            raise ValueError("kind is required")
        safe_title = safe_text(title) or safe_kind
        sess = (session_id or "").strip() or "default"
        ch = (channel or "").strip() or "unknown"
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        now = time.time()
        tid = task_id or uuid.uuid4().hex
        payload_json = safe_json(dict(payload or {}))
        extra_json = safe_json(dict(extra or {}))
        safe_key = (idempotency_key or "").strip() or None
        safe_fp = (fingerprint or "").strip() or None
        with self._lock:
            if safe_key is not None:
                existing = self._conn.execute(
                    """
                    SELECT id, fingerprint FROM tasks
                    WHERE session_id = ? AND idempotency_key = ?
                    """,
                    (sess, safe_key),
                ).fetchone()
                if existing is not None:
                    existing_id = str(existing["id"])
                    existing_fp = existing["fingerprint"]
                    if safe_fp is not None and existing_fp != safe_fp:
                        raise IdempotencyConflict(existing_id, safe_key)
                    loaded = self._get_locked(existing_id)
                    if loaded is not None:
                        return loaded
            try:
                self._conn.execute(
                    """
                    INSERT INTO tasks (
                      id, kind, title, payload_json, status, parent_id,
                      session_id, channel, attempts, max_attempts,
                      result_json, error_code, error_message, resume_token_json,
                      created_at, updated_at, started_at, finished_at, extra_json,
                      notes_json, idempotency_key, fingerprint, progress_json
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      NULL, NULL, ?, '[]', ?, ?, '{}'
                    )
                    """,
                    (
                        tid,
                        safe_kind,
                        safe_title,
                        payload_json,
                        TaskStatus.QUEUED.value,
                        parent_id,
                        sess,
                        ch,
                        0,
                        int(max_attempts),
                        "{}",
                        None,
                        None,
                        None,
                        now,
                        now,
                        extra_json,
                        safe_key,
                        safe_fp,
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                # Concurrent insert raced us — re-fetch and honour replay.
                if safe_key is not None:
                    existing = self._conn.execute(
                        """
                        SELECT id FROM tasks
                        WHERE session_id = ? AND idempotency_key = ?
                        """,
                        (sess, safe_key),
                    ).fetchone()
                    if existing is not None:
                        loaded = self._get_locked(str(existing["id"]))
                        if loaded is not None:
                            return loaded
                raise
        loaded = self._get_locked(tid)
        if loaded is None:
            raise TaskNotFound(tid)
        return loaded

    # ── Read ──────────────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            return self._get_locked(task_id)

    def get_task_or_raise(self, task_id: str) -> Task:
        loaded = self.get_task(task_id)
        if loaded is None:
            raise TaskNotFound(task_id)
        return loaded

    def list_tasks(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        session_id: str | None = None,
        before: float | None = None,
        limit: int = 100,
    ) -> list[Task]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if before is not None:
            clauses.append("updated_at < ?")
            params.append(float(before))
        safe_limit = min(max(int(limit), 1), 200)
        query = "SELECT * FROM tasks"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(safe_limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_row_to_task(r) for r in rows]

    def status_counts(
        self,
        *,
        session_id: str | None = None,
    ) -> dict[str, int]:
        params: list[Any] = []
        where = ""
        if session_id:
            where = " WHERE session_id = ?"
            params.append(session_id)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT status, COUNT(*) AS n FROM tasks{where} "
                "GROUP BY status",
                params,
            ).fetchall()
        counts = {s.value: 0 for s in TaskStatus}
        for r in rows:
            counts[str(r["status"])] = int(r["n"])
        return counts

    # ── Mutations ─────────────────────────────────────────────────────

    def update_task(self, task_id: str, patch: TaskUpdate) -> Task:
        """Apply ``patch`` to ``task_id``.

        The patch supports a ``_UNSET`` sentinel for ``status`` /
        ``result`` / ``error_code`` / ``error_message`` / ``resume_token``
        to mean "explicitly clear this column to NULL". This is what
        ``retry`` uses to wipe stale error state.

        ``BEGIN IMMEDIATE`` + a single ``UPDATE`` keeps the read-modify-
        write atomic within the SQLite file. Concurrent writers will
        serialise on the WAL lock and either see the post-update state
        or fail with the helper's contract.
        """
        existing = self.get_task_or_raise(task_id)
        target_status = (
            existing.status if patch.status is _UNSET else
            patch.status if patch.status is not None else
            existing.status
        )
        if target_status != existing.status:
            assert_transition(existing.status, target_status)
        now = time.time()

        started_at = existing.started_at
        finished_at = existing.finished_at
        attempts = existing.attempts

        if target_status == TaskStatus.RUNNING.value:
            attempts = existing.attempts + 1
            if started_at is None or patch.reset_started_at:
                started_at = now
            finished_at = None
        if patch.clear_started_at:
            started_at = None
        if patch.clear_finished_at:
            finished_at = None
        if target_status in TERMINAL_OR_PARKED:
            finished_at = finished_at or now

        sets: list[str] = ["status = ?", "updated_at = ?"]
        params: list[Any] = [target_status, now]

        # ``_UNSET`` → SQL NULL; ``None`` → no-op; ``dict`` / str → write.
        if patch.result is _UNSET:
            sets.append("result_json = ?")
            params.append("{}")
        elif patch.result is not None:
            sets.append("result_json = ?")
            params.append(safe_json(patch.result))

        if patch.error_code is _UNSET:
            sets.append("error_code = ?")
            params.append(None)
        elif patch.error_code is not None:
            sets.append("error_code = ?")
            params.append(patch.error_code)

        if patch.error_message is _UNSET:
            sets.append("error_message = ?")
            params.append(None)
        elif patch.error_message is not None:
            sets.append("error_message = ?")
            params.append(patch.error_message)

        if patch.resume_token is _UNSET:
            sets.append("resume_token_json = ?")
            params.append(None)
        elif patch.resume_token is not None:
            sets.append("resume_token_json = ?")
            params.append(safe_json(patch.resume_token))

        if patch.progress is not None:
            merged = dict(existing.progress if hasattr(existing, "progress") else {})
            merged.update(dict(patch.progress))
            sets.append("progress_json = ?")
            params.append(safe_json(merged))

        if patch.session_id is not None:
            sets.append("session_id = ?")
            params.append((patch.session_id or "").strip() or "default")

        if started_at != existing.started_at:
            sets.append("started_at = ?")
            params.append(started_at)
        if finished_at != existing.finished_at:
            sets.append("finished_at = ?")
            params.append(finished_at)
        if attempts != existing.attempts:
            sets.append("attempts = ?")
            params.append(int(attempts))

        params.append(task_id)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                if patch.note:
                    self._append_note_locked(
                        task_id, existing.status, target_status, patch.note
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return self.get_task_or_raise(task_id)

    # ── Atomic state transitions ─────────────────────────────────────
    # These wrap ``update_task`` with SQL-level CAS guards so duplicate
    # requests cannot produce duplicate side effects.

    def claim(self, task_id: str, *, note: str | None = None) -> Task:
        """Atomic ``queued/needs_input → running``.

        Refuses (raises) when:
        - the task is already running (duplicate claim).
        - the task is in a terminal state.
        - ``attempts >= max_attempts`` (exhausted).
        """
        with self._lock:
            existing = self._get_locked(task_id)
            if existing is None:
                raise TaskNotFound(task_id)
            if existing.status not in {
                TaskStatus.QUEUED.value,
                TaskStatus.NEEDS_INPUT.value,
            }:
                raise InvalidTaskTransition(existing.status, TaskStatus.RUNNING.value)
            if existing.attempts >= existing.max_attempts:
                raise AttemptsExhausted(
                    existing.attempts, existing.max_attempts
                )
            rowcount = self._conn.execute(
                """
                UPDATE tasks SET status = ?,
                                 attempts = attempts + 1,
                                 started_at = COALESCE(started_at, ?),
                                 finished_at = NULL,
                                 updated_at = ?
                WHERE id = ?
                  AND status IN (?, ?)
                  AND attempts < max_attempts
                """,
                (
                    TaskStatus.RUNNING.value,
                    now := time.time(),
                    now,
                    task_id,
                    TaskStatus.QUEUED.value,
                    TaskStatus.NEEDS_INPUT.value,
                ),
            ).rowcount
            if rowcount == 0:
                # Lost the race with another worker / status changed.
                refreshed = self._get_locked(task_id)
                cur = refreshed.status if refreshed else "missing"
                raise InvalidTaskTransition(cur, TaskStatus.RUNNING.value)
            if note:
                self._append_note_locked(
                    task_id,
                    existing.status,
                    TaskStatus.RUNNING.value,
                    note,
                )
            self._conn.commit()
            refreshed = self._get_locked(task_id)
            assert refreshed is not None
            return refreshed

    def request_input(
        self,
        task_id: str,
        *,
        prompt: str,
        resume_token: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> Task:
        token_payload: dict[str, Any] = {"prompt": prompt}
        if resume_token:
            token_payload["context"] = dict(resume_token)
        return self.update_task(
            task_id,
            TaskUpdate(
                status=TaskStatus.NEEDS_INPUT.value,
                resume_token=token_payload,
                note=note or prompt[:160],
            ),
        )

    def provide_input(
        self,
        task_id: str,
        *,
        input_payload: Mapping[str, Any],
        note: str | None = None,
    ) -> Task:
        return self.update_task(
            task_id,
            TaskUpdate(
                status=TaskStatus.RUNNING.value,
                resume_token={"input": dict(input_payload)},
                reset_started_at=True,
                note=note,
            ),
        )

    def complete(
        self,
        task_id: str,
        *,
        result: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> Task:
        """Atomic ``running → done``.

        Refuses (raises) if the task is not currently running — duplicate
        ``complete`` calls become a 409 ``already_terminal`` rather than
        silently overwriting a prior result.
        """
        result_payload = dict(result or {})
        with self._lock:
            existing = self._get_locked(task_id)
            if existing is None:
                raise TaskNotFound(task_id)
            if existing.status == TaskStatus.DONE.value:
                # Idempotent replay only when result matches verbatim.
                if existing.result_summary == result_payload:
                    return existing
                raise InvalidTaskTransition(
                    existing.status, TaskStatus.DONE.value
                )
            if existing.status != TaskStatus.RUNNING.value:
                raise InvalidTaskTransition(
                    existing.status, TaskStatus.DONE.value
                )
            now = time.time()
            rowcount = self._conn.execute(
                """
                UPDATE tasks SET status = ?,
                                 result_json = ?,
                                 error_code = NULL,
                                 error_message = NULL,
                                 finished_at = COALESCE(finished_at, ?),
                                 updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    TaskStatus.DONE.value,
                    safe_json(result_payload),
                    now,
                    now,
                    task_id,
                    TaskStatus.RUNNING.value,
                ),
            ).rowcount
            if rowcount == 0:
                refreshed = self._get_locked(task_id)
                cur = refreshed.status if refreshed else "missing"
                raise InvalidTaskTransition(cur, TaskStatus.DONE.value)
            if note:
                self._append_note_locked(
                    task_id,
                    existing.status,
                    TaskStatus.DONE.value,
                    note,
                )
            self._conn.commit()
            refreshed = self._get_locked(task_id)
            assert refreshed is not None
            return refreshed

    def fail(
        self,
        task_id: str,
        *,
        error_code: str,
        error_message: str | None = None,
        note: str | None = None,
    ) -> Task:
        """Atomic ``running | needs_input → failed``.

        Records an ``attempt_failed`` event into ``notes`` for structured
        error history. ``note`` defaults to a human-readable summary so
        callers that omit it still get a useful history row.
        """
        safe_error_code = safe_text(error_code) or "unknown"
        safe_error_message = (
            safe_text(error_message) if error_message is not None else ""
        )
        with self._lock:
            existing = self._get_locked(task_id)
            if existing is None:
                raise TaskNotFound(task_id)
            if existing.status not in {
                TaskStatus.RUNNING.value,
                TaskStatus.NEEDS_INPUT.value,
            }:
                raise InvalidTaskTransition(
                    existing.status, TaskStatus.FAILED.value
                )
            now = time.time()
            rowcount = self._conn.execute(
                """
                UPDATE tasks SET status = ?,
                                 error_code = ?,
                                 error_message = ?,
                                 finished_at = COALESCE(finished_at, ?),
                                 updated_at = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    TaskStatus.FAILED.value,
                    safe_error_code,
                    safe_error_message,
                    now,
                    now,
                    task_id,
                    TaskStatus.RUNNING.value,
                    TaskStatus.NEEDS_INPUT.value,
                ),
            ).rowcount
            if rowcount == 0:
                refreshed = self._get_locked(task_id)
                cur = refreshed.status if refreshed else "missing"
                raise InvalidTaskTransition(cur, TaskStatus.FAILED.value)
            self._append_attempt_failed_locked(
                task_id,
                attempts=existing.attempts,
                error_code=safe_error_code,
                error_message=safe_error_message,
                at=now,
            )
            if note:
                self._append_note_locked(
                    task_id,
                    existing.status,
                    TaskStatus.FAILED.value,
                    note,
                )
            else:
                self._append_note_locked(
                    task_id,
                    existing.status,
                    TaskStatus.FAILED.value,
                    f"attempt_failed: {safe_error_code}",
                )
            self._conn.commit()
            refreshed = self._get_locked(task_id)
            assert refreshed is not None
            return refreshed

    def update_progress(
        self,
        task_id: str,
        *,
        progress: Mapping[str, Any],
        note: str | None = None,
    ) -> Task:
        """Merge ``progress`` into the task's ``progress_json``.

        Allowed while the task is in any non-terminal state. Refuses on
        done/failed/cancelled so progress cannot be retroactively written.
        """
        with self._lock:
            existing = self._get_locked(task_id)
            if existing is None:
                raise TaskNotFound(task_id)
            if existing.status in TERMINAL_OR_PARKED and existing.status != TaskStatus.DONE.value:
                raise InvalidTaskTransition(
                    existing.status, existing.status
                )
            if existing.status == TaskStatus.DONE.value:
                # Idempotent: replay same progress returns existing row.
                if dict(existing.progress) == dict(progress):
                    return existing
                raise InvalidTaskTransition(
                    existing.status, existing.status
                )
            merged = dict(existing.progress)
            merged.update(dict(progress))
            now = time.time()
            self._conn.execute(
                "UPDATE tasks SET progress_json = ?, updated_at = ? WHERE id = ?",
                (safe_json(merged), now, task_id),
            )
            if note:
                self._append_note_locked(
                    task_id, existing.status, existing.status, note
                )
            self._conn.commit()
            refreshed = self._get_locked(task_id)
            assert refreshed is not None
            return refreshed

    def cancel(self, task_id: str, *, note: str | None = None) -> Task:
        existing = self.get_task_or_raise(task_id)
        if existing.status in TERMINAL_OR_PARKED:
            return existing
        return self.update_task(
            task_id,
            TaskUpdate(
                status=TaskStatus.CANCELLED.value,
                note=note or "cancelled by operator",
            ),
        )

    def retry(
        self,
        task_id: str,
        *,
        note: str | None = None,
    ) -> Task:
        """``failed | cancelled → queued`` while clearing stale attempt state.

        Uses the ``_UNSET`` sentinel to truly wipe previous error code,
        message, result, resume token and timestamps so the next attempt
        starts clean. Attempts counter is NOT incremented here — only a
        successful ``claim`` advances it. ``max_attempts`` is preserved
        so the executor still has a budget.
        """
        existing = self.get_task_or_raise(task_id)
        if not is_parked(existing.status):
            raise InvalidTaskTransition(existing.status, TaskStatus.QUEUED.value)
        return self.update_task(
            task_id,
            TaskUpdate(
                status=TaskStatus.QUEUED.value,
                result=_UNSET,
                error_code=_UNSET,
                error_message=_UNSET,
                resume_token=_UNSET,
                clear_started_at=True,
                clear_finished_at=True,
                note=note or "retry queued",
            ),
        )

    def error_history(self, task_id: str) -> list[dict[str, Any]]:
        """Return structured ``attempt_failed`` events for the task."""
        with self._lock:
            row = self._conn.execute(
                "SELECT notes_json FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if not row:
            return []
        notes = _decode_notes(row["notes_json"])
        return [n for n in notes if n.get("event") == "attempt_failed"]

    # ── Recovery ─────────────────────────────────────────────────────

    def recover_orphaned_running(
        self,
        *,
        into: str = TaskStatus.NEEDS_INPUT.value,
        reason: str = "service_restart",
    ) -> list[Task]:
        """Reset any pre-restart ``running`` rows to ``needs_input``.

        They look in-progress after a crash, but no worker holds them.
        Returning the list lets the caller surface a "n recovered" log line
        or push a notification to the affected sessions.
        """
        if into not in _ALLOWED[TaskStatus.RUNNING.value]:
            raise ValueError(f"refusing recovery into {into!r}")
        recovered: list[Task] = []
        now = time.time()
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = ?",
                (TaskStatus.RUNNING.value,),
            ).fetchall()
            for row in rows:
                task = _row_to_task(row)
                merged_result = dict(task.result_summary)
                merged_result["resume_reason"] = reason
                merged_result["resumed_at"] = now
                self._conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, updated_at = ?, finished_at = NULL,
                        error_code = NULL, error_message = ?,
                        result_json = ?, attempts = attempts + 1
                    WHERE id = ?
                    """,
                    (
                        into,
                        now,
                        reason,
                        safe_json(merged_result),
                        task.id,
                    ),
                )
                self._append_note_locked(
                    task.id,
                    TaskStatus.RUNNING.value,
                    into,
                    f"recovery: {reason}",
                )
                refreshed = self._get_locked(task.id)
                if refreshed is not None:
                    recovered.append(refreshed)
            self._conn.commit()
        return recovered

    # ── Internals ────────────────────────────────────────────────────

    def _append_note_locked(
        self, task_id: str, from_status: str, to_status: str, note: str
    ) -> None:
        row = self._conn.execute(
            "SELECT notes_json FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        notes = _decode_notes(row["notes_json"] if row else None)
        notes.append(
            {
                "at": time.time(),
                "from": from_status,
                "to": to_status,
                "note": safe_text(note),
            }
        )
        self._conn.execute(
            "UPDATE tasks SET notes_json = ?, updated_at = updated_at WHERE id = ?",
            (json.dumps(notes, ensure_ascii=False), task_id),
        )

    def _append_attempt_failed_locked(
        self,
        task_id: str,
        *,
        attempts: int,
        error_code: str,
        error_message: str,
        at: float,
    ) -> None:
        row = self._conn.execute(
            "SELECT notes_json FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        notes = _decode_notes(row["notes_json"] if row else None)
        notes.append(
            {
                "event": "attempt_failed",
                "at": at,
                "attempt": int(attempts),
                "error_code": safe_text(error_code),
                "error_message": safe_text(error_message),
            }
        )
        self._conn.execute(
            "UPDATE tasks SET notes_json = ?, updated_at = updated_at WHERE id = ?",
            (json.dumps(notes, ensure_ascii=False), task_id),
        )

    def list_notes(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT notes_json FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if not row:
            return []
        return _decode_notes(row["notes_json"])

    def _get_locked(self, task_id: str) -> Task | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return _row_to_task(row) if row else None

    def close(self) -> None:
        if self._closed:
            return
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def clear(self, session_id: str | None = None) -> int:
        with self._lock:
            if session_id is None:
                cursor = self._conn.execute("DELETE FROM tasks")
            else:
                sid = (session_id or "").strip() or "default"
                cursor = self._conn.execute(
                    "DELETE FROM tasks WHERE session_id = ?", (sid,)
                )
            self._conn.commit()
            return cursor.rowcount


def _row_to_task(row: sqlite3.Row) -> Task:
    keys = row.keys()
    return Task(
        id=str(row["id"]),
        kind=str(row["kind"]),
        title=str(row["title"] or ""),
        payload=_decode_dict(row["payload_json"]),
        status=str(row["status"]),
        parent_id=row["parent_id"],
        session_id=str(row["session_id"] or "default"),
        channel=str(row["channel"] or "unknown"),
        attempts=int(row["attempts"] or 0),
        max_attempts=int(row["max_attempts"] or 1),
        result_summary=_decode_dict(row["result_json"]),
        error_code=row["error_code"],
        error_message=row["error_message"],
        resume_token=_decode_dict(row["resume_token_json"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        started_at=(
            None if row["started_at"] is None else float(row["started_at"])
        ),
        finished_at=(
            None if row["finished_at"] is None else float(row["finished_at"])
        ),
        extra=_decode_dict(row["extra_json"]),
        notes=_decode_notes(row["notes_json"] if "notes_json" in keys else None),
        idempotency_key=(
            row["idempotency_key"] if "idempotency_key" in keys else None
        ),
        fingerprint=row["fingerprint"] if "fingerprint" in keys else None,
        progress=_decode_dict(
            row["progress_json"] if "progress_json" in keys else None
        ),
    )


__all__ = [
    "AttemptsExhausted",
    "IdempotencyConflict",
    "InvalidTaskTransition",
    "TASK_STATUSES",
    "Task",
    "TaskNotFound",
    "TaskStatus",
    "TaskStore",
    "TaskUpdate",
    "assert_transition",
    "is_parked",
    "is_terminal",
]
