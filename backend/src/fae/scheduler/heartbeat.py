"""Heartbeat loop scaffold (Phase 4.1 / Q.4).

Wired when SCHEDULER_ENABLED=true. Until then this module is unused at runtime.
"""

from __future__ import annotations

import inspect
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

from fae.scheduler.activity import ActivityTracker
from fae.scheduler.delivery import in_quiet_hours
from fae.scheduler.proactive import OutreachPolicy, should_outreach
from fae.scheduler.store import NotificationPrefs, ScheduleStore

logger = logging.getLogger("fae.scheduler.heartbeat")

OutreachHandler = Callable[[str], Awaitable[None]]
OpenTopicChecker = Callable[[str], bool | Awaitable[bool]]
PrefsGetter = Callable[[], NotificationPrefs]


class HeartbeatLoop:
    """Poll activity every ``interval_seconds`` and invoke outreach when eligible."""

    def __init__(
        self,
        activity: ActivityTracker,
        *,
        interval_seconds: float = 30.0,
        policy: OutreachPolicy | None = None,
        on_outreach: OutreachHandler | None = None,
        open_topic_checker: OpenTopicChecker | None = None,
        store: ScheduleStore | None = None,
        prefs_getter: PrefsGetter | None = None,
    ) -> None:
        self.activity = activity
        self.interval_seconds = interval_seconds
        self.policy = policy or OutreachPolicy()
        self.on_outreach = on_outreach
        self.open_topic_checker = open_topic_checker or (lambda _sid: False)
        self._store = store
        self.prefs_getter = prefs_getter
        self._last_outreach_at: dict[str, float] = {}
        self._outreach_day: dict[str, str] = {}
        self._outreach_count: dict[str, int] = {}
        if store is not None:
            self.hydrate(store)

    def bind_store(self, store: ScheduleStore) -> None:
        self._store = store
        self.hydrate(store)

    def hydrate(self, store: ScheduleStore | None = None) -> None:
        src = store or self._store
        if src is None:
            return
        for sid, (day, count, last_at) in src.list_outreach_state().items():
            if day:
                self._outreach_day[sid] = day
            self._outreach_count[sid] = count
            if last_at is not None:
                self._last_outreach_at[sid] = last_at

    def _day_key(self, now: float) -> str:
        return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")

    def _persist_outreach(self, session_id: str) -> None:
        if self._store is None:
            return
        self._store.set_outreach_state(
            session_id,
            day=self._outreach_day.get(session_id, self._day_key(time.time())),
            count=self._outreach_count.get(session_id, 0),
            last_at=self._last_outreach_at.get(session_id),
        )

    async def _has_open_topic(self, session_id: str) -> bool:
        result = self.open_topic_checker(session_id)
        if inspect.isawaitable(result):
            return bool(await result)
        return bool(result)

    def _prefs(self) -> NotificationPrefs:
        if self.prefs_getter is not None:
            return self.prefs_getter()
        if self._store is not None:
            return self._store.get_prefs()
        return NotificationPrefs()

    async def evaluate(self, session_id: str, *, now: float) -> bool:
        prefs = self._prefs()
        idle = self.activity.idle_seconds(session_id, now=now)
        day = self._day_key(now)
        if self._outreach_day.get(session_id) != day:
            self._outreach_day[session_id] = day
            self._outreach_count[session_id] = 0
            self._persist_outreach(session_id)
        last = self._last_outreach_at.get(session_id)
        since = (now - last) if last is not None else None
        return should_outreach(
            idle_seconds=idle,
            seconds_since_last_outreach=since,
            outreach_count_today=self._outreach_count.get(session_id, 0),
            has_open_topic=await self._has_open_topic(session_id),
            policy=self.policy,
            proactive_enabled=prefs.proactive_enabled,
            in_quiet_hours=in_quiet_hours(
                prefs.quiet_start_hour, prefs.quiet_end_hour
            ),
        )

    async def tick(self, *, now: float | None = None) -> list[str]:
        t = float(now if now is not None else time.time())
        prefs = self._prefs()
        if not prefs.proactive_enabled:
            return []
        if in_quiet_hours(prefs.quiet_start_hour, prefs.quiet_end_hour):
            return []

        fired: list[str] = []
        for sid in self.activity.sessions():
            if not await self.evaluate(sid, now=t):
                continue
            fired.append(sid)
            self._last_outreach_at[sid] = t
            self._outreach_count[sid] = self._outreach_count.get(sid, 0) + 1
            day = self._day_key(t)
            self._outreach_day[sid] = day
            self._persist_outreach(sid)
            if self.on_outreach is not None:
                await self.on_outreach(sid)
            logger.info("proactive outreach eligible session=%s", sid)
        return fired
