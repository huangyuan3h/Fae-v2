"""SQLite-backed memory store (LETTA_MODE=embedded).

Implements the same surface as LettaMemoryClient for offline M2-1 / tests
without pulling the official Letta Docker image.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fae.memory.core_budget import (
    clip_current_for_prompt,
    identity_fact_boost,
    truncate_current,
)
from fae.memory.defaults import DEFAULT_CURRENT, DEFAULT_HUMAN, DEFAULT_PERSONA
from fae.memory.recall_store import RecallStore
from fae.memory.schemas import FactIn, FactOut, RecallTurn, UserProfile

logger = logging.getLogger("fae.memory.embedded")


class EmbeddedMemoryClient:
    """Local persistence for core blocks + facts; recall via shared RecallStore."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        agent_name: str = "fae-main",
        recall_store: RecallStore | None = None,
        current_char_limit: int = 2000,
    ) -> None:
        self.db_path = Path(db_path)
        self.agent_name = agent_name
        self._agent_id: str | None = None
        self._recall = recall_store
        self._current_char_limit = current_char_limit
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=3000")
        self._init_schema()

    @property
    def agent_id(self) -> str | None:
        return self._agent_id

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                  id TEXT PRIMARY KEY,
                  name TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS blocks (
                  agent_id TEXT NOT NULL,
                  label TEXT NOT NULL,
                  value TEXT NOT NULL,
                  PRIMARY KEY (agent_id, label)
                );
                CREATE TABLE IF NOT EXISTS facts (
                  id TEXT PRIMARY KEY,
                  agent_id TEXT NOT NULL,
                  content TEXT NOT NULL,
                  tags TEXT NOT NULL,
                  session_id TEXT,
                  created_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    async def ensure_agent(self) -> str:
        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute(
                "SELECT id FROM agents WHERE name = ?", (self.agent_name,)
            ).fetchone()
            if row:
                self._agent_id = row["id"]
            else:
                agent_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO agents (id, name) VALUES (?, ?)",
                    (agent_id, self.agent_name),
                )
                for label, value in (
                    ("persona", DEFAULT_PERSONA),
                    ("human", DEFAULT_HUMAN),
                    ("current", DEFAULT_CURRENT),
                ):
                    cur.execute(
                        "INSERT INTO blocks (agent_id, label, value) VALUES (?, ?, ?)",
                        (agent_id, label, value),
                    )
                self._conn.commit()
                self._agent_id = agent_id
                logger.info(
                    "Embedded agent created name=%s id=%s",
                    self.agent_name,
                    agent_id,
                )
            return self._agent_id

    def _require_agent(self) -> str:
        if not self._agent_id:
            raise RuntimeError("ensure_agent() must be called first")
        return self._agent_id

    def _get_block(self, label: str) -> str:
        agent_id = self._require_agent()
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM blocks WHERE agent_id = ? AND label = ?",
                (agent_id, label),
            ).fetchone()
        return row["value"] if row else ""

    def _set_block(self, label: str, value: str) -> None:
        agent_id = self._require_agent()
        text = value
        if label == "current":
            text = truncate_current(value, char_limit=self._current_char_limit)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO blocks (agent_id, label, value) VALUES (?, ?, ?)
                ON CONFLICT(agent_id, label) DO UPDATE SET value = excluded.value
                """,
                (agent_id, label, text),
            )
            self._conn.commit()

    async def get_block(self, label: str) -> str:
        return self._get_block(label)

    async def set_block(self, label: str, value: str) -> None:
        self._set_block(label, value)

    async def save_fact(self, fact: FactIn) -> FactOut:
        agent_id = self._require_agent()
        fact_id = str(uuid.uuid4())
        created = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO facts (id, agent_id, content, tags, session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    agent_id,
                    fact.content,
                    json.dumps(fact.tags),
                    fact.session_id,
                    created,
                ),
            )
            self._conn.commit()
        return FactOut(
            id=fact_id,
            content=fact.content,
            tags=list(fact.tags),
            session_id=fact.session_id,
            created_at=datetime.fromisoformat(created),
        )

    def _fact_from_row(self, row: sqlite3.Row) -> FactOut:
        return FactOut(
            id=row["id"],
            content=row["content"],
            tags=json.loads(row["tags"] or "[]"),
            session_id=row["session_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    async def search(self, query: str, *, top_k: int = 10) -> list[FactOut]:
        agent_id = self._require_agent()
        q = (query or "").strip().lower()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, content, tags, session_id, created_at
                FROM facts WHERE agent_id = ?
                ORDER BY created_at DESC
                """,
                (agent_id,),
            ).fetchall()
        scored: list[tuple[int, sqlite3.Row]] = []
        for row in rows:
            content = row["content"].lower()
            tags = json.loads(row["tags"] or "[]")
            score = identity_fact_boost(tags)
            if not q:
                score = max(score, 1)
            else:
                for token in q.split():
                    if token and token in content:
                        score += 2
                if q in content:
                    score += 3
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._fact_from_row(row) for _, row in scored[:top_k]]

    async def list_facts(
        self, *, limit: int = 50, query: str | None = None
    ) -> list[FactOut]:
        return await self.search(query or "", top_k=max(1, limit))

    async def update_fact(self, fact_id: str, fact: FactIn) -> FactOut:
        agent_id = self._require_agent()
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM facts WHERE agent_id = ? AND id = ?",
                (agent_id, fact_id),
            ).fetchone()
            if row is None:
                raise KeyError(fact_id)
            self._conn.execute(
                """
                UPDATE facts SET content = ?, tags = ?, session_id = ?
                WHERE agent_id = ? AND id = ?
                """,
                (
                    fact.content,
                    json.dumps(fact.tags),
                    fact.session_id,
                    agent_id,
                    fact_id,
                ),
            )
            self._conn.commit()
            updated = self._conn.execute(
                """
                SELECT id, content, tags, session_id, created_at
                FROM facts WHERE id = ?
                """,
                (fact_id,),
            ).fetchone()
        return self._fact_from_row(updated)

    async def delete_fact(self, fact_id: str) -> bool:
        agent_id = self._require_agent()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM facts WHERE agent_id = ? AND id = ?",
                (agent_id, fact_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    async def delete_all_facts(self) -> int:
        agent_id = self._require_agent()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM facts WHERE agent_id = ?", (agent_id,)
            )
            self._conn.commit()
            return cur.rowcount

    async def delete_session_facts(self, session_id: str) -> int:
        agent_id = self._require_agent()
        sid = (session_id or "").strip() or "default"
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM facts WHERE agent_id = ? AND session_id = ?",
                (agent_id, sid),
            )
            self._conn.commit()
            return cur.rowcount

    async def update_user(self, profile: UserProfile) -> UserProfile:
        from fae.memory.profile_block import merge_human_profile

        existing = self._get_block("human")
        text = merge_human_profile(
            existing,
            display_name=profile.display_name,
            preferences=profile.preferences,
            notes=profile.notes,
        )
        self._set_block("human", text)
        return profile

    def _require_recall(self) -> RecallStore:
        if self._recall is None:
            raise RuntimeError("RecallStore not configured on EmbeddedMemoryClient")
        return self._recall

    async def append_recall(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        self._require_recall().append(session_id, user_text, assistant_text)

    async def list_recall(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> list[RecallTurn]:
        return self._require_recall().list_hot(session_id, limit=limit)

    async def recall_for_prompt(
        self,
        query: str,
        *,
        session_id: str | None = None,
        top_k: int = 10,
        recent_limit: int = 10,
    ) -> str:
        persona = self._get_block("persona").strip()
        human = self._get_block("human").strip()
        current = clip_current_for_prompt(self._get_block("current").strip())
        parts: list[str] = []
        if persona:
            parts.append(f"[persona]\n{persona}")
        if human:
            parts.append(f"[human]\n{human}")
        if current:
            parts.append(f"[current]\n{current}")
        if session_id:
            turns = await self.list_recall(session_id, limit=recent_limit)
            if turns:
                lines = [
                    f"User: {t.user_text}\nAssistant: {t.assistant_text}"
                    for t in turns
                ]
                parts.append("[recent_turns]\n" + "\n---\n".join(lines))
        facts = await self.search(query, top_k=top_k)
        if facts:
            # Identity-tagged facts already boosted in search; keep that order.
            lines = "\n".join(f"- {f.content}" for f in facts)
            parts.append(f"[facts]\n{lines}")
        return "\n\n".join(parts)

    async def close(self) -> None:
        with self._lock:
            self._conn.close()
        logger.debug("EmbeddedMemoryClient closed path=%s", self.db_path)
