"""SQLite-backed memory store (LETTA_MODE=embedded).

Implements the same surface as LettaMemoryClient for offline M2-1 / tests
without pulling the official Letta Docker image.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fae.memory.core_budget import truncate_current
from fae.memory.recall_store import RecallStore
from fae.memory.schemas import FactIn, FactOut, RecallTurn, UserProfile

logger = logging.getLogger("fae.memory.embedded")

_DEFAULT_PERSONA = (
    "You are FAE, a concise bilingual voice assistant with long-term memory. "
    "Use remembered facts about the user when relevant."
)
_DEFAULT_HUMAN = "Unknown user. Learn and remember their name and preferences."
_DEFAULT_CURRENT = ""


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
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    @property
    def agent_id(self) -> str | None:
        return self._agent_id

    def _init_schema(self) -> None:
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
                ("persona", _DEFAULT_PERSONA),
                ("human", _DEFAULT_HUMAN),
                ("current", _DEFAULT_CURRENT),
            ):
                cur.execute(
                    "INSERT INTO blocks (agent_id, label, value) VALUES (?, ?, ?)",
                    (agent_id, label, value),
                )
            self._conn.commit()
            self._agent_id = agent_id
            logger.info("Embedded agent created name=%s id=%s", self.agent_name, agent_id)
        return self._agent_id

    def _require_agent(self) -> str:
        if not self._agent_id:
            raise RuntimeError("ensure_agent() must be called first")
        return self._agent_id

    def _get_block(self, label: str) -> str:
        agent_id = self._require_agent()
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

    async def search(self, query: str, *, top_k: int = 10) -> list[FactOut]:
        agent_id = self._require_agent()
        q = (query or "").strip().lower()
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
            score = 0
            if not q:
                score = 1
            else:
                for token in q.split():
                    if token and token in content:
                        score += 2
                if q in content:
                    score += 3
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[FactOut] = []
        for _, row in scored[:top_k]:
            out.append(
                FactOut(
                    id=row["id"],
                    content=row["content"],
                    tags=json.loads(row["tags"] or "[]"),
                    session_id=row["session_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return out

    async def update_user(self, profile: UserProfile) -> UserProfile:
        lines: list[str] = []
        if profile.display_name:
            lines.append(f"Name: {profile.display_name}")
        for key, value in profile.preferences.items():
            lines.append(f"{key}: {value}")
        if profile.notes:
            lines.append(profile.notes)
        # Merge with existing human block — keep prior lines not overwritten.
        existing = self._get_block("human")
        if profile.display_name and "Name:" in existing:
            rebuilt: list[str] = []
            for line in existing.splitlines():
                if line.startswith("Name:"):
                    rebuilt.append(f"Name: {profile.display_name}")
                else:
                    rebuilt.append(line)
            # Ensure Name line exists
            if not any(l.startswith("Name:") for l in rebuilt):
                rebuilt.insert(0, f"Name: {profile.display_name}")
            text = "\n".join(rebuilt)
        else:
            text = "\n".join(lines) if lines else existing or _DEFAULT_HUMAN
            if profile.display_name and "Name:" not in text:
                text = f"Name: {profile.display_name}\n{text}".strip()
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
        human = self._get_block("human").strip()
        current = self._get_block("current").strip()
        parts: list[str] = []
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
            lines = "\n".join(f"- {f.content}" for f in facts)
            parts.append(f"[facts]\n{lines}")
        return "\n\n".join(parts)

    async def close(self) -> None:
        self._conn.close()
        logger.debug("EmbeddedMemoryClient closed path=%s", self.db_path)
