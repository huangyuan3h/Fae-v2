"""Episodic memory — life events + links (Phase 2.3b)."""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fae.memory.schemas import EpisodeEvent, EpisodeLink

logger = logging.getLogger("fae.memory.episodic")


@dataclass(frozen=True)
class DetectedEvent:
    kind: str
    summary: str


# Heuristic life-event markers (zh + en). LLM tagging can replace later.
_EVENT_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"(搬家|搬到|搬去|搬进)"), "moved", "User moved / is relocating"),
    (re.compile(r"(换了工作|入职|离职|新工作|跳槽)"), "job_change", "User job change"),
    (re.compile(r"(结婚|订婚|离婚)"), "relationship", "User relationship milestone"),
    (re.compile(r"(毕业|开学)"), "education", "User education milestone"),
    (re.compile(r"(生病|住院|手术)"), "health", "User health event"),
    (re.compile(r"(?i)\b(i moved|we moved|relocated)\b"), "moved", "User moved / is relocating"),
    (
        re.compile(r"(?i)\b(new job|got hired|quit my job|changed jobs)\b"),
        "job_change",
        "User job change",
    ),
    (
        re.compile(r"(?i)\b(got married|engaged|divorced)\b"),
        "relationship",
        "User relationship milestone",
    ),
)


def detect_life_events(user_text: str) -> list[DetectedEvent]:
    """Return zero or more life events inferred from a user utterance."""
    text = (user_text or "").strip()
    if not text:
        return []
    found: list[DetectedEvent] = []
    seen_kinds: set[str] = set()
    for pattern, kind, label in _EVENT_PATTERNS:
        if kind in seen_kinds:
            continue
        if pattern.search(text):
            seen_kinds.add(kind)
            snippet = text if len(text) <= 120 else text[:117] + "..."
            found.append(DetectedEvent(kind=kind, summary=f"{label}: {snippet}"))
    return found


class EpisodicStore:
    """SQLite event log with links to facts / archival / recall turns."""

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
                CREATE TABLE IF NOT EXISTS events (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  summary TEXT NOT NULL,
                  raw_text TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_session
                  ON events (session_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS event_links (
                  event_id TEXT NOT NULL,
                  target_kind TEXT NOT NULL,
                  target_id TEXT NOT NULL,
                  PRIMARY KEY (event_id, target_kind, target_id),
                  FOREIGN KEY (event_id) REFERENCES events(id)
                );
                CREATE INDEX IF NOT EXISTS idx_links_target
                  ON event_links (target_kind, target_id);
                """
            )
            self._conn.commit()

    def add_event(
        self,
        *,
        session_id: str,
        kind: str,
        summary: str,
        raw_text: str = "",
    ) -> EpisodeEvent:
        sid = (session_id or "").strip() or "default"
        event_id = str(uuid.uuid4())
        created = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO events (id, session_id, kind, summary, raw_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, sid, kind, summary, raw_text or "", created),
            )
            self._conn.commit()
        return EpisodeEvent(
            id=event_id,
            session_id=sid,
            kind=kind,
            summary=summary,
            raw_text=raw_text or "",
            created_at=datetime.fromisoformat(created),
        )

    def link(
        self,
        event_id: str,
        target_kind: str,
        target_id: str,
    ) -> EpisodeLink:
        kind = (target_kind or "").strip().lower() or "fact"
        tid = (target_id or "").strip()
        if not tid:
            raise ValueError("target_id required")
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO event_links (event_id, target_kind, target_id)
                VALUES (?, ?, ?)
                """,
                (event_id, kind, tid),
            )
            self._conn.commit()
        return EpisodeLink(event_id=event_id, target_kind=kind, target_id=tid)

    def links_for_event(self, event_id: str) -> list[EpisodeLink]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, target_kind, target_id FROM event_links
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchall()
        return [
            EpisodeLink(
                event_id=r["event_id"],
                target_kind=r["target_kind"],
                target_id=r["target_id"],
            )
            for r in rows
        ]

    def events_for_target(
        self, target_kind: str, target_id: str
    ) -> list[EpisodeEvent]:
        """Reverse lookup: memory → events (bidirectional)."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT e.id, e.session_id, e.kind, e.summary, e.raw_text, e.created_at
                FROM events e
                JOIN event_links l ON l.event_id = e.id
                WHERE l.target_kind = ? AND l.target_id = ?
                ORDER BY e.created_at DESC
                """,
                (target_kind, target_id),
            ).fetchall()
        return [_row_to_event(r) for r in rows]

    def list_events(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
        query: str | None = None,
    ) -> list[EpisodeEvent]:
        lim = max(1, limit)
        q = (query or "").strip().lower()
        with self._lock:
            if session_id is not None:
                sid = (session_id or "").strip() or "default"
                rows = self._conn.execute(
                    """
                    SELECT id, session_id, kind, summary, raw_text, created_at
                    FROM events WHERE session_id = ?
                    ORDER BY created_at DESC, id DESC LIMIT ?
                    """,
                    (sid, lim * 3 if q else lim),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT id, session_id, kind, summary, raw_text, created_at
                    FROM events
                    ORDER BY created_at DESC, id DESC LIMIT ?
                    """,
                    (lim * 3 if q else lim,),
                ).fetchall()
        events = [_row_to_event(r) for r in rows]
        if q:
            events = [
                e
                for e in events
                if q in e.summary.lower()
                or q in e.raw_text.lower()
                or q in e.kind.lower()
            ][:lim]
        else:
            events = events[:lim]
        for ev in events:
            ev.links = self.links_for_event(ev.id)
        return events

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()
        return int(row["n"] if row else 0)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        logger.debug("EpisodicStore closed path=%s", self.db_path)


def _row_to_event(row: sqlite3.Row) -> EpisodeEvent:
    return EpisodeEvent(
        id=row["id"],
        session_id=row["session_id"],
        kind=row["kind"],
        summary=row["summary"],
        raw_text=row["raw_text"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def format_events_for_prompt(events: list[EpisodeEvent]) -> str:
    if not events:
        return ""
    lines: list[str] = []
    for ev in events:
        link_bits = ", ".join(
            f"{lk.target_kind}:{lk.target_id[:8]}" for lk in ev.links[:5]
        )
        suffix = f" (links: {link_bits})" if link_bits else ""
        lines.append(f"- [{ev.kind}] {ev.summary}{suffix}")
    return "[events]\n" + "\n".join(lines)
