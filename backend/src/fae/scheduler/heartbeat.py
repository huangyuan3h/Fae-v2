"""Heartbeat loop scaffold (Phase 4.1).

Wired when SCHEDULER_ENABLED=true. Until then this module is unused at runtime.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fae.scheduler.activity import ActivityTracker
from fae.scheduler.proactive import OutreachPolicy, should_outreach

logger = logging.getLogger("fae.scheduler.heartbeat")

OutreachHandler = Callable[[str], Awaitable[None]]


class HeartbeatLoop:
    """Poll activity every ``interval_seconds`` and invoke outreach when eligible.

    Full APScheduler wiring lands in Phase 4.1; this class holds the check logic.
    """

    def __init__(
        self,
        activity: ActivityTracker,
        *,
        interval_seconds: float = 30.0,
        policy: OutreachPolicy | None = None,
        on_outreach: OutreachHandler | None = None,
        open_topic_checker: Callable[[str], bool] | None = None,
    ) -> None:
        self.activity = activity
        self.interval_seconds = interval_seconds
        self.policy = policy or OutreachPolicy()
        self.on_outreach = on_outreach
        self.open_topic_checker = open_topic_checker or (lambda _sid: False)
        self._last_outreach_at: dict[str, float] = {}
        self._outreach_day: dict[str, str] = {}
        self._outreach_count: dict[str, int] = {}

    def _day_key(self, now: float) -> str:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")

    def evaluate(self, session_id: str, *, now: float) -> bool:
        idle = self.activity.idle_seconds(session_id, now=now)
        day = self._day_key(now)
        if self._outreach_day.get(session_id) != day:
            self._outreach_day[session_id] = day
            self._outreach_count[session_id] = 0
        last = self._last_outreach_at.get(session_id)
        since = (now - last) if last is not None else None
        return should_outreach(
            idle_seconds=idle,
            seconds_since_last_outreach=since,
            outreach_count_today=self._outreach_count.get(session_id, 0),
            has_open_topic=self.open_topic_checker(session_id),
            policy=self.policy,
        )

    async def tick(self, *, now: float | None = None) -> list[str]:
        import time

        t = float(now if now is not None else time.time())
        fired: list[str] = []
        for sid in self.activity.sessions():
            if not self.evaluate(sid, now=t):
                continue
            fired.append(sid)
            self._last_outreach_at[sid] = t
            self._outreach_count[sid] = self._outreach_count.get(sid, 0) + 1
            if self.on_outreach is not None:
                await self.on_outreach(sid)
            logger.info("proactive outreach eligible session=%s", sid)
        return fired
