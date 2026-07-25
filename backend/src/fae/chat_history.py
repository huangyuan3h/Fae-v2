from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("fae.chat_history")


@dataclass(frozen=True)
class ChatHistoryTurn:
    id: str
    session_id: str
    user_text: str
    assistant_text: str
    created_at: datetime


class ChatHistoryStore:
    def __init__(self, db_path: str | Path, retention_days: int = 7) -> None:
        self.db_path = Path(db_path)
        self.retention_days = retention_days
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._closed = False
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=3000")
        self._init_schema()

    @property
    def closed(self) -> bool:
        return self._closed

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_history_turns (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  user_text TEXT NOT NULL,
                  assistant_text TEXT NOT NULL,
                  created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_history_session_created
                  ON chat_history_turns (session_id, created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_chat_history_created
                  ON chat_history_turns (created_at);

                CREATE TABLE IF NOT EXISTS chat_history_sessions (
                  session_id TEXT PRIMARY KEY,
                  title TEXT NOT NULL DEFAULT '',
                  pinned INTEGER NOT NULL DEFAULT 0,
                  first_seen_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    def append(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
        *,
        created_at: datetime | None = None,
    ) -> ChatHistoryTurn:
        sid = (session_id or "").strip() or "default"
        created = created_at or datetime.now(UTC)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        else:
            created = created.astimezone(UTC)
        turn = ChatHistoryTurn(
            id=str(uuid.uuid4()),
            session_id=sid,
            user_text=user_text or "",
            assistant_text=assistant_text or "",
            created_at=created,
        )
        ts = turn.created_at.timestamp()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO chat_history_turns
                  (id, session_id, user_text, assistant_text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    turn.id,
                    turn.session_id,
                    turn.user_text,
                    turn.assistant_text,
                    ts,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO chat_history_sessions
                  (session_id, title, pinned, first_seen_at, updated_at)
                VALUES (?, '', 0, ?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (turn.session_id, ts, ts),
            )
            self._conn.execute(
                """
                UPDATE chat_history_sessions
                SET title = CASE
                      WHEN title = '' THEN ?
                      ELSE title
                    END,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    self._auto_title(turn.user_text),
                    ts,
                    turn.session_id,
                ),
            )
            self._conn.commit()
        return turn

    def list(
        self,
        session_id: str,
        *,
        limit: int = 100,
        now: datetime | None = None,
        before: datetime | str | None = None,
    ) -> list[ChatHistoryTurn]:
        turns, _ = self.list_with_more(
            session_id, limit=limit, now=now, before=before,
        )
        return turns

    def list_with_more(
        self,
        session_id: str,
        *,
        limit: int = 100,
        now: datetime | None = None,
        before: datetime | str | None = None,
    ) -> tuple[list[ChatHistoryTurn], bool]:
        sid = (session_id or "").strip() or "default"
        cutoff = self._cutoff(now)
        page_size = max(1, int(limit))
        cutoff_clause = ""
        before_clause = ""
        params: list[object] = []
        with self._lock:
            pinned_row = self._conn.execute(
                "SELECT pinned FROM chat_history_sessions WHERE session_id = ?",
                (sid,),
            ).fetchone()
            is_pinned = bool(pinned_row and pinned_row["pinned"])
            params.append(sid)
            if not is_pinned:
                params.append(cutoff.timestamp())
                cutoff_clause = " AND t.created_at >= ?"
            if before is not None:
                before_dt = self._coerce_dt(before)
                params.append(before_dt.timestamp())
                before_clause = " AND t.created_at < ?"
            params.append(page_size + 1)
            rows = self._conn.execute(
                f"""
                SELECT t.id, t.session_id, t.user_text, t.assistant_text, t.created_at
                FROM chat_history_turns AS t
                WHERE t.session_id = ?{cutoff_clause}{before_clause}
                ORDER BY t.created_at DESC, t.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        return [self._row_to_turn(row) for row in reversed(rows)], has_more

    def list_sessions(
        self,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, object]]:
        cutoff = self._cutoff(now)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT s.session_id AS session_id,
                       s.title AS title,
                       s.pinned AS pinned,
                       t.turn_count AS turn_count,
                       t.last_created_at AS last_created_at
                FROM chat_history_sessions AS s
                INNER JOIN (
                  SELECT session_id,
                         COUNT(*) AS turn_count,
                         MAX(created_at) AS last_created_at
                  FROM chat_history_turns
                  WHERE created_at >= ?
                  GROUP BY session_id
                ) AS t ON t.session_id = s.session_id
                ORDER BY s.pinned DESC,
                         t.last_created_at DESC,
                         s.session_id ASC
                """,
                (cutoff.timestamp(),),
            ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            results.append(
                {
                    "session_id": row["session_id"],
                    "title": row["title"] or "",
                    "pinned": bool(row["pinned"]),
                    "turn_count": int(row["turn_count"]),
                    "last_activity_at": datetime.fromtimestamp(
                        float(row["last_created_at"]), UTC
                    ).isoformat(),
                }
            )
        return results

    def update_session_title(self, session_id: str, title: str) -> bool:
        sid = (session_id or "").strip() or "default"
        clean = (title or "").strip()[:120]
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE chat_history_sessions
                SET title = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (clean, datetime.now(UTC).timestamp(), sid),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def set_session_pinned(self, session_id: str, pinned: bool) -> bool:
        sid = (session_id or "").strip() or "default"
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE chat_history_sessions
                SET pinned = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (1 if pinned else 0, datetime.now(UTC).timestamp(), sid),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def ensure_session(self, session_id: str) -> None:
        sid = (session_id or "").strip() or "default"
        ts = datetime.now(UTC).timestamp()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO chat_history_sessions
                  (session_id, title, pinned, first_seen_at, updated_at)
                VALUES (?, '', 0, ?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (sid, ts, ts),
            )
            self._conn.commit()

    def delete_expired(self, *, now: datetime | None = None) -> int:
        cutoff = self._cutoff(now)
        with self._lock:
            cursor = self._conn.execute(
                """
                DELETE FROM chat_history_turns
                WHERE created_at < ?
                  AND session_id NOT IN (
                    SELECT session_id FROM chat_history_sessions WHERE pinned = 1
                  )
                """,
                (cutoff.timestamp(),),
            )
            self._conn.commit()
            return cursor.rowcount

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM chat_history_turns"
            ).fetchone()
        return int(row["n"] if row else 0)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def _cutoff(self, now: datetime | None) -> datetime:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        else:
            current = current.astimezone(UTC)
        return current - timedelta(days=self.retention_days)

    @staticmethod
    def _auto_title(text: str) -> str:
        raw = (text or "").strip().replace("\n", " ").replace("\r", " ")
        raw = " ".join(raw.split())
        if not raw:
            return ""
        if len(raw) <= 28:
            return raw
        return raw[:27].rstrip() + "…"

    @staticmethod
    def _coerce_dt(value: datetime | str) -> datetime:
        if isinstance(value, datetime):
            dt = value
        else:
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            else:
                text = re.sub(
                    r"(\d{2}:\d{2})$",
                    lambda m: "+" + m.group(1),
                    text,
                )
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                try:
                    dt = datetime.fromtimestamp(float(text), UTC)
                except ValueError as e:
                    raise ValueError(f"invalid before cursor: {value!r}") from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return dt

    @staticmethod
    def _row_to_turn(row: sqlite3.Row) -> ChatHistoryTurn:
        return ChatHistoryTurn(
            id=row["id"],
            session_id=row["session_id"],
            user_text=row["user_text"],
            assistant_text=row["assistant_text"],
            created_at=datetime.fromtimestamp(float(row["created_at"]), UTC),
        )


async def chat_history_cleanup_loop(
    store: ChatHistoryStore,
    interval_seconds: float,
) -> None:
    while True:
        try:
            deleted = await asyncio.to_thread(store.delete_expired)
            if deleted:
                logger.info("Deleted %s expired chat history turns", deleted)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat history cleanup failed")
        await asyncio.sleep(interval_seconds)
