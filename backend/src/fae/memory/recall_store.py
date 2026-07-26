"""Shared SQLite store for hot recall turns (Phase 2.3).

Used by both EmbeddedMemoryClient and LettaMemoryClient so session
bucketing is identical regardless of Letta mode.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fae.memory.schemas import RecallTurn

logger = logging.getLogger("fae.memory.recall_store")


class RecallStore:
    """Hot-window conversation turns keyed by session_id."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=3000")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS recall_turns (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  user_text TEXT NOT NULL,
                  assistant_text TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  archived_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_recall_hot
                  ON recall_turns (session_id, created_at)
                  WHERE archived_at IS NULL;
                """
            )
            self._conn.commit()

    def append(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> RecallTurn:
        sid = (session_id or "").strip() or "default"
        turn_id = str(uuid.uuid4())
        created = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO recall_turns
                  (id, session_id, user_text, assistant_text, created_at, archived_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (turn_id, sid, user_text or "", assistant_text or "", created),
            )
            self._conn.commit()
        return RecallTurn(
            id=turn_id,
            session_id=sid,
            user_text=user_text or "",
            assistant_text=assistant_text or "",
            created_at=datetime.fromisoformat(created),
        )

    def count_hot(self, session_id: str) -> int:
        sid = (session_id or "").strip() or "default"
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM recall_turns
                WHERE session_id = ? AND archived_at IS NULL
                """,
                (sid,),
            ).fetchone()
        return int(row["n"] if row else 0)

    def list_hot(self, session_id: str, *, limit: int = 20) -> list[RecallTurn]:
        sid = (session_id or "").strip() or "default"
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, session_id, user_text, assistant_text, created_at
                FROM recall_turns
                WHERE session_id = ? AND archived_at IS NULL
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (sid, max(1, limit)),
            ).fetchall()
        return [
            RecallTurn(
                id=row["id"],
                session_id=row["session_id"],
                user_text=row["user_text"],
                assistant_text=row["assistant_text"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in reversed(rows)
        ]

    def peek_oldest_hot(self, session_id: str, n: int) -> list[RecallTurn]:
        """Return oldest n hot turns without marking them archived."""
        sid = (session_id or "").strip() or "default"
        if n <= 0:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, session_id, user_text, assistant_text, created_at
                FROM recall_turns
                WHERE session_id = ? AND archived_at IS NULL
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (sid, n),
            ).fetchall()
        return [_row_to_turn(row) for row in rows]

    def mark_archived(self, turn_ids: list[str]) -> None:
        if not turn_ids:
            return
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.executemany(
                "UPDATE recall_turns SET archived_at = ? WHERE id = ?",
                [(now, i) for i in turn_ids],
            )
            self._conn.commit()

    def pop_oldest_hot(self, session_id: str, n: int) -> list[RecallTurn]:
        """Mark the oldest n hot turns as archived and return them."""
        turns = self.peek_oldest_hot(session_id, n)
        if turns:
            self.mark_archived([t.id for t in turns])
        return turns

    def total_hot(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM recall_turns WHERE archived_at IS NULL"
            ).fetchone()
        return int(row["n"] if row else 0)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        logger.debug("RecallStore closed path=%s", self.db_path)

    def clear(self, session_id: str | None = None) -> int:
        with self._lock:
            if session_id is None:
                cursor = self._conn.execute("DELETE FROM recall_turns")
            else:
                sid = (session_id or "").strip() or "default"
                cursor = self._conn.execute(
                    "DELETE FROM recall_turns WHERE session_id = ?", (sid,)
                )
            self._conn.commit()
            return cursor.rowcount


def _row_to_turn(row: sqlite3.Row) -> RecallTurn:
    return RecallTurn(
        id=row["id"],
        session_id=row["session_id"],
        user_text=row["user_text"],
        assistant_text=row["assistant_text"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
