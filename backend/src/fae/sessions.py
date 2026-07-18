"""In-memory session registry.

Phase 2 will attach `agent_id` / transcript cursors in `meta` and optionally
mirror sessions into Redis / Letta. No TTL yet — fine for single-process demo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Session:
    id: str
    created_at: str
    mode: str = "text"  # text | voice
    # transport, room_url, agent_id, etc.
    meta: dict[str, str] = field(default_factory=dict)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, *, mode: str = "text") -> Session:
        session = Session(
            id=str(uuid.uuid4()),
            created_at=datetime.now(UTC).isoformat(),
            mode=mode,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)
