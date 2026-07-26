from __future__ import annotations

import asyncio
import json
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

logger = logging.getLogger("fae.tool_audit")


@dataclass(frozen=True)
class ToolAuditEvent:
    id: str
    call_id: str
    session_id: str
    channel: str
    channel_id: str | None
    tool_name: str
    phase: str
    arguments: str
    result: str
    ok: bool | None
    error_code: str | None
    approval_status: str
    approval_id: str | None
    turn_id: str | None
    started_at: float
    finished_at: float | None
    duration_ms: float | None


def _result_error_code(result: str) -> str | None:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return "invalid_tool_result"
    if not isinstance(payload, dict):
        return "invalid_tool_result"
    error = payload.get("error") or payload.get("code")
    return str(error) if error else None


class ToolAuditStore:
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
                CREATE TABLE IF NOT EXISTS tool_audit_events (
                  id TEXT PRIMARY KEY,
                  call_id TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  channel TEXT NOT NULL,
                  channel_id TEXT,
                  tool_name TEXT NOT NULL,
                  phase TEXT NOT NULL,
                  arguments TEXT NOT NULL DEFAULT '',
                  result TEXT NOT NULL DEFAULT '',
                  ok INTEGER,
                  error_code TEXT,
                  approval_status TEXT NOT NULL DEFAULT 'not_required',
                  started_at REAL NOT NULL,
                  finished_at REAL,
                  duration_ms REAL
                );
                CREATE INDEX IF NOT EXISTS idx_tool_audit_session_created
                  ON tool_audit_events (session_id, started_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_tool_audit_call
                  ON tool_audit_events (call_id);
                CREATE INDEX IF NOT EXISTS idx_tool_audit_tool_created
                  ON tool_audit_events (tool_name, started_at DESC);
                """
            )
            columns = {
                str(row[1])
                for row in self._conn.execute(
                    "PRAGMA table_info(tool_audit_events)"
                ).fetchall()
            }
            if "approval_status" not in columns:
                self._conn.execute(
                    "ALTER TABLE tool_audit_events ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'not_required'"
                )
            if "approval_id" not in columns:
                self._conn.execute(
                    "ALTER TABLE tool_audit_events ADD COLUMN approval_id TEXT"
                )
            if "turn_id" not in columns:
                self._conn.execute(
                    "ALTER TABLE tool_audit_events ADD COLUMN turn_id TEXT"
                )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_audit_turn
                  ON tool_audit_events (turn_id)
                  WHERE turn_id IS NOT NULL
                """
            )
            self._conn.commit()

    def record_event(
        self,
        event: Mapping[str, Any],
        *,
        session_id: str = "default",
        channel: str = "unknown",
        channel_id: str | None = None,
        turn_id: str | None = None,
    ) -> ToolAuditEvent:
        event_id = safe_text(event.get("id")) or str(uuid.uuid4())
        call_id = event_id
        sid = (session_id or "").strip() or "default"
        source = (channel or "").strip() or "unknown"
        tool_name = safe_text(event.get("name")) or "unknown"
        raw_phase = safe_text(event.get("phase"))
        arguments = safe_json(event.get("arguments", ""))
        approval_status = safe_text(event.get("approval_status")) or "not_required"
        approval_id = safe_text(event.get("approval_id")) or None
        turn_id_clean = (turn_id or "").strip() or None
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tool_audit_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if raw_phase == "start":
                started_at = now
                if row is None:
                    self._conn.execute(
                        """
                        INSERT INTO tool_audit_events
                        (id, call_id, session_id, channel, channel_id, tool_name, phase,
                         arguments, approval_status, approval_id, turn_id, started_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'start', ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            call_id,
                            sid,
                            source,
                            channel_id,
                            tool_name,
                            arguments,
                            approval_status,
                            approval_id,
                            turn_id_clean,
                            started_at,
                        ),
                    )
                else:
                    started_at = float(row["started_at"])
                    self._conn.execute(
                        "UPDATE tool_audit_events SET turn_id = ? WHERE id = ?",
                        (turn_id_clean, event_id),
                    )
            else:
                phase = "done" if bool(event.get("ok")) else "error"
                result = safe_json(event.get("result", ""))
                error_code = (
                    safe_text(event.get("error_code"))
                    or (None if phase == "done" else _result_error_code(result))
                )
                started_at = float(row["started_at"]) if row is not None else now
                finished_at = now
                duration_ms = max(0.0, (finished_at - started_at) * 1000)
                if row is None:
                    self._conn.execute(
                        """
                        INSERT INTO tool_audit_events
                        (id, call_id, session_id, channel, channel_id, tool_name, phase,
                         arguments, result, ok, error_code, approval_status, approval_id,
                         turn_id, started_at, finished_at, duration_ms)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            call_id,
                            sid,
                            source,
                            channel_id,
                            tool_name,
                            phase,
                            arguments,
                            result,
                            int(bool(event.get("ok"))),
                            error_code,
                            approval_status,
                            approval_id,
                            turn_id_clean,
                            started_at,
                            finished_at,
                            duration_ms,
                        ),
                    )
                else:
                    # Preserve existing turn_id from the start row unless the
                    # terminal event explicitly carries a new one.
                    merged_turn_id = turn_id_clean or row["turn_id"]
                    self._conn.execute(
                        """
                        UPDATE tool_audit_events
                        SET phase = ?, result = ?, ok = ?, error_code = ?,
                            approval_status = ?, approval_id = ?, turn_id = ?,
                            finished_at = ?, duration_ms = ?
                        WHERE id = ?
                        """,
                        (
                            phase,
                            result,
                            int(bool(event.get("ok"))),
                            error_code,
                            approval_status,
                            approval_id,
                            merged_turn_id,
                            finished_at,
                            duration_ms,
                            event_id,
                        ),
                    )
            self._conn.commit()
            saved = self._conn.execute(
                "SELECT * FROM tool_audit_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        if saved is None:
            raise RuntimeError("tool audit event was not persisted")
        return self._row_to_event(saved)

    def list_events(
        self,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        channel: str | None = None,
        phase: str | None = None,
        turn_id: str | None = None,
        before: float | None = None,
        limit: int = 50,
    ) -> list[ToolAuditEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if tool_name:
            clauses.append("tool_name = ?")
            params.append(tool_name)
        if channel:
            clauses.append("channel = ?")
            params.append(channel)
        if phase:
            clauses.append("phase = ?")
            params.append(phase)
        if turn_id:
            clauses.append("turn_id = ?")
            params.append(turn_id)
        if before is not None:
            clauses.append("started_at < ?")
            params.append(before)
        safe_limit = min(max(int(limit), 1), 200)
        query = "SELECT * FROM tool_audit_events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY started_at DESC, id DESC LIMIT ?"
        params.append(safe_limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    def clear(self, session_id: str | None = None) -> int:
        with self._lock:
            if session_id is None:
                cursor = self._conn.execute(
                    "DELETE FROM tool_audit_events"
                )
            else:
                sid = (session_id or "").strip() or "default"
                cursor = self._conn.execute(
                    "DELETE FROM tool_audit_events WHERE session_id = ?",
                    (sid,),
                )
            self._conn.commit()
            return cursor.rowcount

    def _row_to_event(self, row: sqlite3.Row) -> ToolAuditEvent:
        ok = row["ok"]
        return ToolAuditEvent(
            id=str(row["id"]),
            call_id=str(row["call_id"]),
            session_id=str(row["session_id"]),
            channel=str(row["channel"]),
            channel_id=row["channel_id"],
            tool_name=str(row["tool_name"]),
            phase=str(row["phase"]),
            arguments=str(row["arguments"] or ""),
            result=str(row["result"] or ""),
            ok=None if ok is None else bool(ok),
            error_code=row["error_code"],
            approval_status=str(row["approval_status"] or "not_required"),
            approval_id=row["approval_id"],
            turn_id=row["turn_id"],
            started_at=float(row["started_at"]),
            finished_at=(
                None if row["finished_at"] is None else float(row["finished_at"])
            ),
            duration_ms=(
                None if row["duration_ms"] is None else float(row["duration_ms"])
            ),
        )

    def close(self) -> None:
        if self._closed:
            return
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True


def make_tool_audit_callback(
    store: ToolAuditStore,
    *,
    session_id: str,
    channel: str,
    channel_id: str | None = None,
    turn_id: str | None = None,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    async def on_event(event: dict[str, Any]) -> None:
        if store.closed:
            return
        try:
            await asyncio.to_thread(
                store.record_event,
                event,
                session_id=session_id,
                channel=channel,
                channel_id=channel_id,
                turn_id=turn_id,
            )
        except Exception:
            logger.exception("Tool audit event persist failed")

    return on_event
