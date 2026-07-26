"""Queryable agent execution trace store.

Persists per-turn subagent / tool / skill activation events so that a UI
(future) or operator can replay what happened during a turn after a
refresh / service restart. Distinct from ``fae.tool_audit``: this store
captures the *process* sequence, audit stores the *compliance record*.

Layout:
  - Each ``stream_assistant_turn`` call owns a ``turn_id`` (uuid4 hex),
    propagated as the optional ``trace_turn_id`` kwarg.
  - Three event kinds: ``subagent``, ``tool``, ``skill``.
  - Phases: ``start`` (action begins), ``done`` / ``error`` (terminal).
  - Skips persistence for ``tool`` events when no ``trace_turn_id`` is
    provided — the audit store already records those for compliance;
    without a turn root there is no sequence to reconstruct.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fae.sanitize import safe_json, safe_text

logger = logging.getLogger("fae.agent_trace")

KIND_TOOL = "tool"
KIND_SUBAGENT = "subagent"
KIND_SKILL = "skill"
KIND_APPROVAL = "approval"
_VALID_KINDS = frozenset({KIND_TOOL, KIND_SUBAGENT, KIND_SKILL, KIND_APPROVAL})

PHASE_START = "start"
PHASE_DONE = "done"
PHASE_ERROR = "error"
PHASE_RESULT = "result"
_VALID_PHASES = frozenset({PHASE_START, PHASE_DONE, PHASE_ERROR, PHASE_RESULT})
# ``result`` is the live wire phase emitted by tool/subagent runtimes;
# we treat it as a terminal marker and normalize to PHASE_DONE or
# PHASE_ERROR based on the ``ok`` flag at write time.


@dataclass(frozen=True)
class AgentTraceEvent:
    id: int
    turn_id: str
    session_id: str
    channel: str
    channel_id: str | None
    kind: str
    phase: str
    name: str
    payload: str
    started_at: float
    finished_at: float | None
    duration_ms: float | None
    ok: bool | None
    error_code: str | None


class AgentTraceStore:
    """Append-only log of one-turn execution events."""

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
                CREATE TABLE IF NOT EXISTS agent_trace_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  turn_id TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  channel TEXT NOT NULL,
                  channel_id TEXT,
                  kind TEXT NOT NULL,
                  phase TEXT NOT NULL,
                  name TEXT NOT NULL,
                  payload TEXT NOT NULL DEFAULT '',
                  started_at REAL NOT NULL,
                  finished_at REAL,
                  duration_ms REAL,
                  ok INTEGER,
                  error_code TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_agent_trace_turn
                  ON agent_trace_events (turn_id, started_at, id);
                CREATE INDEX IF NOT EXISTS idx_agent_trace_session_started
                  ON agent_trace_events (session_id, started_at, id);
                """
            )
            columns = {
                str(row[1])
                for row in self._conn.execute(
                    "PRAGMA table_info(agent_trace_events)"
                ).fetchall()
            }
            if "finished_at" not in columns:
                self._conn.execute(
                    "ALTER TABLE agent_trace_events ADD COLUMN finished_at REAL"
                )
            if "duration_ms" not in columns:
                self._conn.execute(
                    "ALTER TABLE agent_trace_events ADD COLUMN duration_ms REAL"
                )
            self._conn.commit()

    def record_event(
        self,
        event: Mapping[str, Any],
        *,
        turn_id: str,
        session_id: str = "default",
        channel: str = "unknown",
        channel_id: str | None = None,
    ) -> AgentTraceEvent | None:
        """Persist one event under ``turn_id``.

        Returns the saved row, or ``None`` when the event should be skipped
        (no turn_id, unknown kind, or store has been closed).
        """
        if self._closed:
            return None
        tid = (turn_id or "").strip()
        if not tid:
            return None
        kind = safe_text(event.get("kind") or event.get("type") or "")
        if kind not in _VALID_KINDS:
            if kind == "tool" or kind == "approval_request" or kind == "approval_resolved":
                # Approval events emit ``type=approval_request`` /
                # ``type=approval_resolved``; still pin them to KIND_APPROVAL.
                kind = KIND_TOOL if kind == "tool" else KIND_APPROVAL
            elif kind == "subagent":
                kind = KIND_SUBAGENT
            elif kind == "approval":
                kind = KIND_APPROVAL
            else:
                return None
        phase = safe_text(event.get("phase"))
        if phase not in _VALID_PHASES:
            return None
        sid = (session_id or "").strip() or "default"
        source = (channel or "").strip() or "unknown"
        name = safe_text(event.get("name")) or "unknown"
        payload = safe_json(event.get("payload", event))
        now = time.time()
        raw_ok = event.get("ok")
        ok_value: int | None = None
        if raw_ok is not None:
            ok_value = 1 if bool(raw_ok) else 0
        error_code = safe_text(event.get("error_code")) or None
        if phase == PHASE_RESULT:
            normalized_phase = PHASE_DONE if ok_value == 1 or raw_ok is True else PHASE_ERROR
        else:
            normalized_phase = phase
        finished_at: float | None = None
        duration_ms: float | None = None
        if normalized_phase in (PHASE_DONE, PHASE_ERROR):
            finished_at = now
            # Lookup the most-recent matching start row to compute elapsed time.
            with self._lock:
                start_row = self._conn.execute(
                    """
                    SELECT started_at FROM agent_trace_events
                    WHERE turn_id = ?
                      AND kind = ?
                      AND name = ?
                      AND phase = 'start'
                      AND id = (
                        SELECT MAX(id) FROM agent_trace_events
                        WHERE turn_id = ?
                          AND kind = ?
                          AND name = ?
                          AND phase = 'start'
                      )
                    """,
                    (tid, kind, name, tid, kind, name),
                ).fetchone()
                if start_row is not None:
                    duration_ms = max(0.0, (finished_at - float(start_row["started_at"])) * 1000)
        if normalized_phase == PHASE_ERROR and not error_code:
            error_code = "tool_failed"
        with self._lock:
            if finished_at is not None:
                start_row = self._conn.execute(
                    """
                    SELECT started_at FROM agent_trace_events
                    WHERE turn_id = ?
                      AND kind = ?
                      AND name = ?
                      AND phase = 'start'
                      AND id = (
                        SELECT MAX(id) FROM agent_trace_events
                        WHERE turn_id = ?
                          AND kind = ?
                          AND name = ?
                          AND phase = 'start'
                      )
                    """,
                    (tid, kind, name, tid, kind, name),
                ).fetchone()
                if start_row is not None:
                    duration_ms = max(
                        0.0, (finished_at - float(start_row["started_at"])) * 1000
                    )
            self._conn.execute(
                """
                INSERT INTO agent_trace_events
                  (turn_id, session_id, channel, channel_id, kind, phase,
                   name, payload, started_at, finished_at, duration_ms,
                   ok, error_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    sid,
                    source,
                    channel_id,
                    kind,
                    normalized_phase,
                    name,
                    payload,
                    now,
                    finished_at,
                    duration_ms,
                    ok_value,
                    error_code,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM agent_trace_events WHERE id = last_insert_rowid()"
            ).fetchone()
            self._conn.commit()
        if row is None:
            return None
        return _row_to_event(row)

    def list_events(
        self,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        kind: str | None = None,
        before: float | None = None,
        limit: int = 200,
    ) -> list[AgentTraceEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if turn_id:
            clauses.append("turn_id = ?")
            params.append(turn_id)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if before is not None:
            clauses.append("started_at < ?")
            params.append(before)
        safe_limit = min(max(int(limit), 1), 500)
        query = "SELECT * FROM agent_trace_events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(safe_limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_row_to_event(row) for row in rows]

    def close(self) -> None:
        if self._closed:
            return
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True


def _row_to_event(row: sqlite3.Row) -> AgentTraceEvent:
    ok_raw = row["ok"]
    return AgentTraceEvent(
        id=int(row["id"]),
        turn_id=str(row["turn_id"]),
        session_id=str(row["session_id"]),
        channel=str(row["channel"]),
        channel_id=row["channel_id"],
        kind=str(row["kind"]),
        phase=str(row["phase"]),
        name=str(row["name"]),
        payload=str(row["payload"] or ""),
        started_at=float(row["started_at"]),
        finished_at=(
            None if row["finished_at"] is None else float(row["finished_at"])
        ),
        duration_ms=(
            None if row["duration_ms"] is None else float(row["duration_ms"])
        ),
        ok=None if ok_raw is None else bool(ok_raw),
        error_code=row["error_code"],
    )


def make_agent_trace_callback(
    store: AgentTraceStore,
    *,
    turn_id: str,
    session_id: str,
    channel: str,
    channel_id: str | None = None,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """Build a callback compatible with ``OnToolEvent`` / ``OnSubagentEvent``.

    The callback filters events by ``kind`` (tool | subagent | skill) and
    silently drops unknown shapes so callers can keep wiring a single
    callback for both trace and audit.
    """

    async def on_event(event: dict[str, Any]) -> None:
        if store.closed:
            return
        try:
            await asyncio.to_thread(
                store.record_event,
                event,
                turn_id=turn_id,
                session_id=session_id,
                channel=channel,
                channel_id=channel_id,
            )
        except Exception:
            logger.exception("Agent trace event persist failed")

    return on_event


def new_turn_id() -> str:
    """Stable per-turn identifier (uuid4 hex, no dashes)."""
    return uuid.uuid4().hex
