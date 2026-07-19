"""Shared last-interaction clock for sleeptime + proactive heartbeat."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fae.scheduler.store import ScheduleStore


class ActivityTracker:
    """Wall-clock timestamps of the last user/agent interaction per session."""

    def __init__(self, store: ScheduleStore | None = None) -> None:
        self._store = store
        self._last: dict[str, float] = {}
        if store is not None:
            self.hydrate(store)

    def bind_store(self, store: ScheduleStore) -> None:
        """Attach SQLite persistence and hydrate missing keys."""
        self._store = store
        self.hydrate(store)

    def hydrate(self, store: ScheduleStore | None = None) -> None:
        src = store or self._store
        if src is None:
            return
        for sid, ts in src.list_activity_last_at().items():
            # Prefer newer in-memory value if already touched this process.
            prev = self._last.get(sid)
            if prev is None or ts > prev:
                self._last[sid] = ts

    def touch(self, session_id: str, *, at: float | None = None) -> None:
        sid = (session_id or "").strip() or "default"
        ts = float(at if at is not None else time.time())
        self._last[sid] = ts
        if self._store is not None:
            self._store.set_activity_last_at(sid, ts)

    def last_at(self, session_id: str) -> float | None:
        sid = (session_id or "").strip() or "default"
        return self._last.get(sid)

    def idle_seconds(self, session_id: str, *, now: float | None = None) -> float | None:
        last = self.last_at(session_id)
        if last is None:
            return None
        return float(now if now is not None else time.time()) - last

    def sessions(self) -> list[str]:
        return sorted(self._last.keys())
