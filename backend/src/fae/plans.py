"""Persistent Plan / Todo state machine.

A Plan is a structured, multi-step workflow the agent commits to for a
complex user request. Plans are persisted in SQLite so they survive
process restarts and session switches — the agent can pick up where it
left off across multiple turns.

A Plan has:
  - ``status``: ``active`` | ``completed`` | ``abandoned``
  - ``steps``: ordered list of ``PlanStep`` rows, each with its own state
  - ``session_id``: scopes the plan to a memory session (cross-turn)

State transitions (PlanStep.status):
    pending     → in_progress | cancelled | blocked
    in_progress → completed | blocked | pending (rollback)
    blocked     → pending (user provided info / agent unblocked)
    completed   → (terminal)
    cancelled   → (terminal)

Only one step per plan may be ``in_progress`` at a time. Server enforces
this in ``claim_step`` to keep the FE preview accurate.

Scope boundaries:
  - This module does not call the LLM. It only stores plans and emits
    status transitions so the agent loop, WS layer and FE can sync.
  - The agent is responsible for calling the ``update_plan`` tool to
    signal progress; the server records it.
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
from typing import Any, Iterable


class PlanStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


PLAN_STATUSES: frozenset[str] = frozenset(s.value for s in PlanStatus)
STEP_STATUSES: frozenset[str] = frozenset(s.value for s in PlanStepStatus)

_STEP_TERMINAL: frozenset[str] = frozenset(
    {PlanStepStatus.COMPLETED.value, PlanStepStatus.CANCELLED.value}
)

STEP_TRANSITIONS: dict[str, frozenset[str]] = {
    PlanStepStatus.PENDING.value: frozenset(
        {
            PlanStepStatus.IN_PROGRESS.value,
            PlanStepStatus.COMPLETED.value,
            PlanStepStatus.BLOCKED.value,
            PlanStepStatus.CANCELLED.value,
        }
    ),
    PlanStepStatus.IN_PROGRESS.value: frozenset(
        {
            PlanStepStatus.COMPLETED.value,
            PlanStepStatus.BLOCKED.value,
            PlanStepStatus.PENDING.value,
        }
    ),
    PlanStepStatus.BLOCKED.value: frozenset(
        {PlanStepStatus.PENDING.value, PlanStepStatus.CANCELLED.value}
    ),
    PlanStepStatus.COMPLETED.value: frozenset(),
    PlanStepStatus.CANCELLED.value: frozenset(),
}


class InvalidPlanTransition(ValueError):
    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(f"invalid plan step transition: {from_status} -> {to_status}")
        self.from_status = from_status
        self.to_status = to_status


def assert_step_transition(from_status: str, to_status: str) -> None:
    if from_status not in STEP_STATUSES:
        raise ValueError(f"unknown source status: {from_status!r}")
    if to_status not in STEP_STATUSES:
        raise ValueError(f"unknown target status: {to_status!r}")
    if to_status not in STEP_TRANSITIONS[from_status]:
        raise InvalidPlanTransition(from_status, to_status)


@dataclass
class PlanStep:
    id: str
    plan_id: str
    index: int
    title: str
    acceptance: str
    status: str
    note: str
    created_at: float
    started_at: float | None
    finished_at: float | None

    @property
    def is_terminal(self) -> bool:
        return self.status in _STEP_TERMINAL


@dataclass
class Plan:
    id: str
    session_id: str
    title: str
    summary: str
    status: str
    created_at: float
    updated_at: float
    finished_at: float | None
    steps: list[PlanStep] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status == PlanStatus.ACTIVE.value

    @property
    def is_terminal(self) -> bool:
        return self.status != PlanStatus.ACTIVE.value

    def progress(self) -> dict[str, int]:
        counts = {s.value: 0 for s in PlanStepStatus}
        for step in self.steps:
            counts[step.status] += 1
        return counts

    def next_pending_index(self) -> int | None:
        for step in self.steps:
            if step.status == PlanStepStatus.PENDING.value:
                return step.index
        return None


def _now() -> float:
    return time.time()


def _gen_id() -> str:
    return uuid.uuid4().hex


class PlanStore:
    """SQLite-backed plan + plan-step store.

    Thread-safe via a single internal lock. All public methods are sync;
    wrap in ``asyncio.to_thread`` from async call sites if needed.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._closed = False
        self._init_schema()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._lock:
            self._closed = True
            try:
                self._conn.close()
            except Exception:
                pass

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS plans (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  title TEXT NOT NULL,
                  summary TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  finished_at REAL
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_plans_session_status
                  ON plans (session_id, status, updated_at DESC)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_steps (
                  id TEXT PRIMARY KEY,
                  plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                  idx INTEGER NOT NULL,
                  title TEXT NOT NULL,
                  acceptance TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL,
                  note TEXT NOT NULL DEFAULT '',
                  created_at REAL NOT NULL,
                  started_at REAL,
                  finished_at REAL
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_plan_steps_plan
                  ON plan_steps (plan_id, idx)
                """
            )

    def create_plan(
        self,
        session_id: str,
        title: str,
        summary: str,
        steps: Iterable[dict[str, str]],
    ) -> Plan:
        """Create a plan and its steps.

        Existing active plans for the session are abandoned (only one
        active plan per session is allowed).
        """
        now = _now()
        plan_id = _gen_id()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            try:
                cur.execute(
                    "UPDATE plans SET status=?, updated_at=?, finished_at=COALESCE(finished_at, ?) "
                    "WHERE session_id=? AND status=?",
                    (
                        PlanStatus.ABANDONED.value,
                        now,
                        now,
                        session_id,
                        PlanStatus.ACTIVE.value,
                    ),
                )
                cur.execute(
                    "INSERT INTO plans (id, session_id, title, summary, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        plan_id,
                        session_id,
                        title,
                        summary,
                        PlanStatus.ACTIVE.value,
                        now,
                        now,
                    ),
                )
                step_rows: list[PlanStep] = []
                for idx, step in enumerate(steps):
                    step_id = _gen_id()
                    cur.execute(
                        "INSERT INTO plan_steps (id, plan_id, idx, title, acceptance, status, note, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            step_id,
                            plan_id,
                            idx,
                            step.get("title", f"Step {idx + 1}"),
                            step.get("acceptance", ""),
                            PlanStepStatus.PENDING.value,
                            "",
                            now,
                        ),
                    )
                    step_rows.append(
                        PlanStep(
                            id=step_id,
                            plan_id=plan_id,
                            index=idx,
                            title=step.get("title", f"Step {idx + 1}"),
                            acceptance=step.get("acceptance", ""),
                            status=PlanStepStatus.PENDING.value,
                            note="",
                            created_at=now,
                            started_at=None,
                            finished_at=None,
                        )
                    )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
        return Plan(
            id=plan_id,
            session_id=session_id,
            title=title,
            summary=summary,
            status=PlanStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
            finished_at=None,
            steps=step_rows,
        )

    def get_active_for_session(self, session_id: str) -> Plan | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, session_id, title, summary, status, created_at, updated_at, finished_at "
                "FROM plans WHERE session_id=? AND status=? ORDER BY created_at DESC LIMIT 1",
                (session_id, PlanStatus.ACTIVE.value),
            )
            row = cur.fetchone()
            if not row:
                return None
            plan = Plan(
                id=row[0],
                session_id=row[1],
                title=row[2],
                summary=row[3],
                status=row[4],
                created_at=row[5],
                updated_at=row[6],
                finished_at=row[7],
                steps=[],
            )
            cur.execute(
                "SELECT id, plan_id, idx, title, acceptance, status, note, created_at, started_at, finished_at "
                "FROM plan_steps WHERE plan_id=? ORDER BY idx ASC",
                (plan.id,),
            )
            for srow in cur.fetchall():
                plan.steps.append(
                    PlanStep(
                        id=srow[0],
                        plan_id=srow[1],
                        index=srow[2],
                        title=srow[3],
                        acceptance=srow[4],
                        status=srow[5],
                        note=srow[6],
                        created_at=srow[7],
                        started_at=srow[8],
                        finished_at=srow[9],
                    )
                )
            return plan

    def get_plan(self, plan_id: str) -> Plan | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, session_id, title, summary, status, created_at, updated_at, finished_at "
                "FROM plans WHERE id=?",
                (plan_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            plan = Plan(
                id=row[0],
                session_id=row[1],
                title=row[2],
                summary=row[3],
                status=row[4],
                created_at=row[5],
                updated_at=row[6],
                finished_at=row[7],
                steps=[],
            )
            cur.execute(
                "SELECT id, plan_id, idx, title, acceptance, status, note, created_at, started_at, finished_at "
                "FROM plan_steps WHERE plan_id=? ORDER BY idx ASC",
                (plan.id,),
            )
            for srow in cur.fetchall():
                plan.steps.append(
                    PlanStep(
                        id=srow[0],
                        plan_id=srow[1],
                        index=srow[2],
                        title=srow[3],
                        acceptance=srow[4],
                        status=srow[5],
                        note=srow[6],
                        created_at=srow[7],
                        started_at=srow[8],
                        finished_at=srow[9],
                    )
                )
            return plan

    def list_steps(self, plan_id: str) -> list[PlanStep]:
        return [s for s in (self.get_plan(plan_id) or Plan(steps=[])).steps]

    def _update_step_status(
        self,
        step_id: str,
        to_status: str,
        *,
        note: str | None = None,
        result: str | None = None,
    ) -> PlanStep:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT plan_id, idx, status FROM plan_steps WHERE id=?",
                (step_id,),
            )
            row = cur.fetchone()
            if not row:
                raise LookupError(f"plan step not found: {step_id}")
            plan_id, idx, current = row
            assert_step_transition(current, to_status)
            now = _now()
            started_at = "started_at" if to_status == PlanStepStatus.IN_PROGRESS.value else None
            finished_at = "finished_at" if to_status in _STEP_TERMINAL or to_status == PlanStepStatus.BLOCKED.value else None
            set_clauses = ["status=?"]
            params: list[Any] = [to_status]
            if note is not None:
                set_clauses.append("note=?")
                params.append(note)
            if started_at:
                set_clauses.append(f"{started_at}=?")
                params.append(now)
            if finished_at:
                set_clauses.append(f"{finished_at}=?")
                params.append(now)
            params.append(step_id)
            params.append(plan_id)
            cur.execute(
                f"UPDATE plan_steps SET {', '.join(set_clauses)} WHERE id=? AND plan_id=?",
                params,
            )
            cur.execute(
                "UPDATE plans SET updated_at=? WHERE id=?",
                (now, plan_id),
            )
            cur.execute(
                "SELECT id, plan_id, idx, title, acceptance, status, note, created_at, started_at, finished_at "
                "FROM plan_steps WHERE id=?",
                (step_id,),
            )
            srow = cur.fetchone()
            return PlanStep(
                id=srow[0],
                plan_id=srow[1],
                index=srow[2],
                title=srow[3],
                acceptance=srow[4],
                status=srow[5],
                note=srow[6],
                created_at=srow[7],
                started_at=srow[8],
                finished_at=srow[9],
            )

    def claim_step(self, step_id: str) -> PlanStep:
        """Transition a step to ``in_progress``.

        Server enforces only one in-progress step per plan: if another
        step is already in_progress, that one is auto-completed (last
        to touch wins) — agents should call ``complete_step`` before
        claiming the next.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT plan_id FROM plan_steps WHERE id=?", (step_id,))
            row = cur.fetchone()
            if not row:
                raise LookupError(f"plan step not found: {step_id}")
            plan_id = row[0]
            now = _now()
            cur.execute(
                "UPDATE plan_steps SET status=?, finished_at=COALESCE(finished_at, ?) "
                "WHERE plan_id=? AND status=?",
                (
                    PlanStepStatus.COMPLETED.value,
                    now,
                    plan_id,
                    PlanStepStatus.IN_PROGRESS.value,
                ),
            )
            cur.execute("UPDATE plans SET updated_at=? WHERE id=?", (now, plan_id))
        return self._update_step_status(step_id, PlanStepStatus.IN_PROGRESS.value)

    def complete_step(self, step_id: str, note: str | None = None) -> PlanStep:
        step = self._update_step_status(step_id, PlanStepStatus.COMPLETED.value, note=note)
        self._maybe_complete_plan(step.plan_id)
        return step

    def block_step(self, step_id: str, reason: str) -> PlanStep:
        return self._update_step_status(step_id, PlanStepStatus.BLOCKED.value, note=reason)

    def unblock_step(self, step_id: str, note: str | None = None) -> PlanStep:
        """Transition a blocked step back to pending.

        ``note`` (when provided) overwrites the existing note so the
        next assistant turn can read the user-provided context directly
        from the step row.
        """
        return self._update_step_status(step_id, PlanStepStatus.PENDING.value, note=note)

    def cancel_step(self, step_id: str, note: str | None = None) -> PlanStep:
        step = self._update_step_status(step_id, PlanStepStatus.CANCELLED.value, note=note)
        self._maybe_complete_plan(step.plan_id)
        return step

    def edit_step(
        self,
        step_id: str,
        *,
        title: str | None = None,
        acceptance: str | None = None,
    ) -> PlanStep:
        """Edit a step's ``title`` / ``acceptance`` in place.

        Allowed only while the step is non-terminal
        (``pending`` / ``in_progress`` / ``blocked``). Does not touch
        ``status``, ``note``, ``idx`` or timestamps so the agent's
        progress view remains stable across edits.

        At least one of ``title`` / ``acceptance`` must be provided.
        Empty strings are normalised to ``""`` so callers can clear
        fields explicitly.
        """
        if title is None and acceptance is None:
            raise ValueError("edit_step: nothing to update")
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT plan_id, status FROM plan_steps WHERE id=?",
                (step_id,),
            )
            row = cur.fetchone()
            if not row:
                raise LookupError(f"plan step not found: {step_id}")
            plan_id, status = row
            if status in _STEP_TERMINAL:
                raise InvalidPlanTransition(status, status)
            now = _now()
            sets: list[str] = []
            params: list[Any] = []
            if title is not None:
                sets.append("title=?")
                params.append(title.strip())
            if acceptance is not None:
                sets.append("acceptance=?")
                params.append(acceptance.strip())
            params += [step_id, plan_id]
            cur.execute(
                f"UPDATE plan_steps SET {', '.join(sets)} WHERE id=? AND plan_id=?",
                params,
            )
            cur.execute(
                "UPDATE plans SET updated_at=? WHERE id=?",
                (now, plan_id),
            )
            cur.execute(
                "SELECT id, plan_id, idx, title, acceptance, status, note, created_at, started_at, finished_at "
                "FROM plan_steps WHERE id=?",
                (step_id,),
            )
            srow = cur.fetchone()
            return PlanStep(
                id=srow[0],
                plan_id=srow[1],
                index=srow[2],
                title=srow[3],
                acceptance=srow[4],
                status=srow[5],
                note=srow[6],
                created_at=srow[7],
                started_at=srow[8],
                finished_at=srow[9],
            )

    def reorder_step(self, step_id: str, new_index: int) -> PlanStep:
        """Move ``step_id`` to ``new_index`` within its plan.

        Allowed only while the step is non-terminal. The schema has no
        ``(plan_id, idx)`` UNIQUE constraint, so we perform a 3-step swap
        inside a single transaction: temporary ``-1`` slot → displace
        the row at ``new_index`` → drop the moved step into place.
        This keeps any concurrent ``SELECT`` consistent and avoids
        transient duplicate idx rows even if another process reads
        mid-transaction (SQLite's WAL serialises writers).

        ``new_index`` is 0-based and must satisfy ``0 <= new_index < N``
        where ``N`` is the step count of the plan. ``note`` / status /
        timestamps are untouched — the agent's progress view is
        preserved across reorder.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT plan_id, idx, status FROM plan_steps WHERE id=?",
                (step_id,),
            )
            row = cur.fetchone()
            if not row:
                raise LookupError(f"plan step not found: {step_id}")
            plan_id, old_idx, status = row
            if status in _STEP_TERMINAL:
                raise InvalidPlanTransition(status, status)
            cur.execute(
                "SELECT COUNT(*) FROM plan_steps WHERE plan_id=?",
                (plan_id,),
            )
            n = int(cur.fetchone()[0])
            if new_index < 0 or new_index >= n:
                raise ValueError(
                    f"reorder_step: new_index {new_index} out of range (0..{n-1})"
                )
            if new_index == old_idx:
                # No-op fast path — just return the current row.
                cur.execute(
                    "SELECT id, plan_id, idx, title, acceptance, status, note, created_at, started_at, finished_at "
                    "FROM plan_steps WHERE id=?",
                    (step_id,),
                )
                srow = cur.fetchone()
                return PlanStep(
                    id=srow[0],
                    plan_id=srow[1],
                    index=srow[2],
                    title=srow[3],
                    acceptance=srow[4],
                    status=srow[5],
                    note=srow[6],
                    created_at=srow[7],
                    started_at=srow[8],
                    finished_at=srow[9],
                )
            now = _now()
            try:
                cur.execute("BEGIN IMMEDIATE")
                # 1) Park the moved step on a sentinel slot so the
                #    subsequent range UPDATE doesn't see its old idx.
                cur.execute(
                    "UPDATE plan_steps SET idx=-1 WHERE id=? AND plan_id=?",
                    (step_id, plan_id),
                )
                # 2) Shift the rows in (old_idx, new_index] (moving
                #    down) or [new_index, old_idx) (moving up) so the
                #    new_index slot becomes free.
                if old_idx < new_index:
                    cur.execute(
                        "UPDATE plan_steps SET idx=idx-1 "
                        "WHERE plan_id=? AND idx > ? AND idx <= ?",
                        (plan_id, old_idx, new_index),
                    )
                else:
                    cur.execute(
                        "UPDATE plan_steps SET idx=idx+1 "
                        "WHERE plan_id=? AND idx >= ? AND idx < ?",
                        (plan_id, new_index, old_idx),
                    )
                # 3) Drop the moved step into new_index.
                cur.execute(
                    "UPDATE plan_steps SET idx=? WHERE id=? AND plan_id=?",
                    (new_index, step_id, plan_id),
                )
                cur.execute(
                    "UPDATE plans SET updated_at=? WHERE id=?",
                    (now, plan_id),
                )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
            cur.execute(
                "SELECT id, plan_id, idx, title, acceptance, status, note, created_at, started_at, finished_at "
                "FROM plan_steps WHERE id=?",
                (step_id,),
            )
            srow = cur.fetchone()
            return PlanStep(
                id=srow[0],
                plan_id=srow[1],
                index=srow[2],
                title=srow[3],
                acceptance=srow[4],
                status=srow[5],
                note=srow[6],
                created_at=srow[7],
                started_at=srow[8],
                finished_at=srow[9],
            )

    def _maybe_complete_plan(self, plan_id: str) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT status FROM plan_steps WHERE plan_id=?",
                (plan_id,),
            )
            statuses = [r[0] for r in cur.fetchall()]
            if not statuses:
                return
            all_done = all(s in _STEP_TERMINAL for s in statuses)
            if all_done:
                now = _now()
                cur.execute(
                    "UPDATE plans SET status=?, updated_at=?, finished_at=? "
                    "WHERE id=? AND status=?",
                    (
                        PlanStatus.COMPLETED.value,
                        now,
                        now,
                        plan_id,
                        PlanStatus.ACTIVE.value,
                    ),
                )

    def append_step_note(self, step_id: str, note: str) -> PlanStep:
        """Append a free-form note to a step without changing its status.

        Useful for capturing user-provided context (e.g. "user replied with
        the missing API key on the next turn") that the agent should see
        when it resumes work on a blocked or pending step.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT plan_id, idx, status, note FROM plan_steps WHERE id=?",
                (step_id,),
            )
            row = cur.fetchone()
            if not row:
                raise LookupError(f"plan step not found: {step_id}")
            plan_id, idx, status, existing = row
            now = _now()
            merged = (existing + "\n" + note).strip() if existing else note.strip()
            cur.execute(
                "UPDATE plan_steps SET note=? WHERE id=? AND plan_id=?",
                (merged, step_id, plan_id),
            )
            cur.execute(
                "UPDATE plans SET updated_at=? WHERE id=?",
                (now, plan_id),
            )
            cur.execute(
                "SELECT id, plan_id, idx, title, acceptance, status, note, created_at, started_at, finished_at "
                "FROM plan_steps WHERE id=?",
                (step_id,),
            )
            srow = cur.fetchone()
            return PlanStep(
                id=srow[0],
                plan_id=srow[1],
                index=srow[2],
                title=srow[3],
                acceptance=srow[4],
                status=srow[5],
                note=srow[6],
                created_at=srow[7],
                started_at=srow[8],
                finished_at=srow[9],
            )

    def abandon_plan(self, plan_id: str) -> None:
        with self._lock:
            cur = self._conn.cursor()
            now = _now()
            cur.execute(
                "UPDATE plans SET status=?, updated_at=?, finished_at=COALESCE(finished_at, ?) "
                "WHERE id=? AND status=?",
                (
                    PlanStatus.ABANDONED.value,
                    now,
                    now,
                    plan_id,
                    PlanStatus.ACTIVE.value,
                ),
            )

    def list_plans_for_session(
        self, session_id: str, *, limit: int = 50
    ) -> list[Plan]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, session_id, title, summary, status, created_at, updated_at, finished_at "
                "FROM plans WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            )
            plans: list[Plan] = []
            for row in cur.fetchall():
                plans.append(
                    Plan(
                        id=row[0],
                        session_id=row[1],
                        title=row[2],
                        summary=row[3],
                        status=row[4],
                        created_at=row[5],
                        updated_at=row[6],
                        finished_at=row[7],
                        steps=[],
                    )
                )
            for plan in plans:
                cur.execute(
                    "SELECT id, plan_id, idx, title, acceptance, status, note, created_at, started_at, finished_at "
                    "FROM plan_steps WHERE plan_id=? ORDER BY idx ASC",
                    (plan.id,),
                )
                for srow in cur.fetchall():
                    plan.steps.append(
                        PlanStep(
                            id=srow[0],
                            plan_id=srow[1],
                            index=srow[2],
                            title=srow[3],
                            acceptance=srow[4],
                            status=srow[5],
                            note=srow[6],
                            created_at=srow[7],
                            started_at=srow[8],
                            finished_at=srow[9],
                        )
                    )
            return plans

    def clear(self, session_id: str | None = None) -> int:
        """Delete all plans (and steps) for a session, or globally.

        Returns the count of plans deleted.
        """
        with self._lock:
            cur = self._conn.cursor()
            if session_id is None:
                cur.execute("SELECT COUNT(*) FROM plans")
                count = cur.fetchone()[0]
                cur.execute("DELETE FROM plan_steps")
                cur.execute("DELETE FROM plans")
                return count
            cur.execute(
                "SELECT id FROM plans WHERE session_id=?",
                (session_id,),
            )
            plan_ids = [r[0] for r in cur.fetchall()]
            if not plan_ids:
                return 0
            placeholders = ",".join("?" for _ in plan_ids)
            cur.execute(
                f"DELETE FROM plan_steps WHERE plan_id IN ({placeholders})",
                plan_ids,
            )
            cur.execute(
                "DELETE FROM plans WHERE session_id=?",
                (session_id,),
            )
            return len(plan_ids)

    def to_dict(self, plan: Plan) -> dict[str, Any]:
        return {
            "id": plan.id,
            "session_id": plan.session_id,
            "title": plan.title,
            "summary": plan.summary,
            "status": plan.status,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
            "finished_at": plan.finished_at,
            "steps": [
                {
                    "id": s.id,
                    "index": s.index,
                    "title": s.title,
                    "acceptance": s.acceptance,
                    "status": s.status,
                    "note": s.note,
                    "created_at": s.created_at,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                }
                for s in plan.steps
            ],
        }