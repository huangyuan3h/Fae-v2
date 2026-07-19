"""Shared last-interaction clock for sleeptime + proactive heartbeat."""

from __future__ import annotations

import time


class ActivityTracker:
    """Wall-clock timestamps of the last user/agent interaction per session."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def touch(self, session_id: str, *, at: float | None = None) -> None:
        sid = (session_id or "").strip() or "default"
        self._last[sid] = float(at if at is not None else time.time())

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
