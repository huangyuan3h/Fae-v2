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

Scope boundaries:
  - This module does not run jobs. It only persists status transitions
    so the rest of the system (HTTP, WS, Telegram, scheduler loop) can
    observe and resume.
  - Retry idempotency keys (next-step TODO) attach to ``Task.id`` so the
    same task row covers multiple attempts.
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
    sanitized by ``safe_json`` before persistence.
    """

    status: str | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    resume_token: dict[str, Any] | None = None
    session_id: str | None = None
    reset_started_at: bool = False
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
                  notes_json TEXT NOT NULL DEFAULT '[]'
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
    ) -> Task:
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
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO tasks (
                  id, kind, title, payload_json, status, parent_id,
                  session_id, channel, attempts, max_attempts,
                  result_json, error_code, error_message, resume_token_json,
                  created_at, updated_at, started_at, finished_at, extra_json,
                  notes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, '[]')
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
                ),
            )
            self._conn.commit()
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
        existing = self.get_task_or_raise(task_id)
        target_status = patch.status or existing.status
        if patch.status and patch.status != existing.status:
            assert_transition(existing.status, patch.status)
        now = time.time()
        result_json = safe_json(patch.result) if patch.result is not None else None
        resume_token_json = (
            safe_json(patch.resume_token)
            if patch.resume_token is not None
            else None
        )
        started_at = existing.started_at
        finished_at = existing.finished_at
        attempts = existing.attempts
        if patch.status == TaskStatus.RUNNING.value:
            attempts = existing.attempts + 1
            started_at = started_at or now
            finished_at = None
        if patch.reset_started_at:
            started_at = now
            finished_at = None
        if patch.status in TERMINAL_OR_PARKED:
            finished_at = finished_at or now

        sets: list[str] = ["status = ?", "updated_at = ?"]
        params: list[Any] = [target_status, now]
        if result_json is not None:
            sets.append("result_json = ?")
            params.append(result_json)
        if patch.error_code is not None:
            sets.append("error_code = ?")
            params.append(patch.error_code or None)
        if patch.error_message is not None:
            sets.append("error_message = ?")
            params.append(patch.error_message or None)
        if resume_token_json is not None:
            sets.append("resume_token_json = ?")
            params.append(resume_token_json)
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
            self._conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            if patch.note:
                self._append_note_locked(
                    task_id, existing.status, target_status, patch.note
                )
            self._conn.commit()
        return self.get_task_or_raise(task_id)

    def claim(self, task_id: str, *, note: str | None = None) -> Task:
        return self.update_task(
            task_id,
            TaskUpdate(status=TaskStatus.RUNNING.value, note=note),
        )

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
        return self.update_task(
            task_id,
            TaskUpdate(
                status=TaskStatus.DONE.value,
                result=dict(result or {}),
                error_code=None,
                error_message=None,
                note=note,
            ),
        )

    def fail(
        self,
        task_id: str,
        *,
        error_code: str,
        error_message: str | None = None,
        note: str | None = None,
    ) -> Task:
        return self.update_task(
            task_id,
            TaskUpdate(
                status=TaskStatus.FAILED.value,
                error_code=error_code,
                error_message=error_message or "",
                note=note,
            ),
        )

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
        existing = self.get_task_or_raise(task_id)
        if not is_parked(existing.status):
            raise InvalidTaskTransition(existing.status, TaskStatus.QUEUED.value)
        return self.update_task(
            task_id,
            TaskUpdate(
                status=TaskStatus.QUEUED.value,
                error_code=None,
                error_message=None,
                note=note or "retry queued",
            ),
        )

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
        notes=_decode_notes(row["notes_json"] if "notes_json" in row.keys() else None),
    )


__all__ = [
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
