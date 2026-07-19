"""Activity / outreach SQLite persistence (Phase Q.4.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.scheduler.activity import ActivityTracker
from fae.scheduler.heartbeat import HeartbeatLoop
from fae.scheduler.proactive import OutreachPolicy
from fae.scheduler.store import NotificationPrefs, ScheduleStore


def test_activity_tracker_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "a.db"
    store = ScheduleStore(db)
    t1 = ActivityTracker(store=store)
    t1.touch("default", at=1_700_000_000.0)
    store.close()

    store2 = ScheduleStore(db)
    t2 = ActivityTracker(store=store2)
    assert t2.last_at("default") == 1_700_000_000.0
    assert t2.idle_seconds("default", now=1_700_000_100.0) == 100.0
    store2.close()


@pytest.mark.asyncio
async def test_outreach_state_persists(tmp_path: Path) -> None:
    db = tmp_path / "o.db"
    store = ScheduleStore(db)
    activity = ActivityTracker(store=store)
    activity.touch("default", at=0.0)
    fired: list[str] = []

    async def on_outreach(sid: str) -> None:
        fired.append(sid)

    hb = HeartbeatLoop(
        activity,
        policy=OutreachPolicy(idle_seconds=10, cooldown_seconds=100, max_per_day=1),
        on_outreach=on_outreach,
        open_topic_checker=lambda _sid: True,
        store=store,
    )
    out = await hb.tick(now=100.0)
    assert out == ["default"]
    store.close()

    store2 = ScheduleStore(db)
    activity2 = ActivityTracker(store=store2)
    hb2 = HeartbeatLoop(
        activity2,
        policy=OutreachPolicy(idle_seconds=10, cooldown_seconds=100, max_per_day=1),
        on_outreach=on_outreach,
        open_topic_checker=lambda _sid: True,
        store=store2,
    )
    # Same UTC day + cooldown → no second fire after restart
    out2 = await hb2.tick(now=150.0)
    assert out2 == []
    store2.close()


@pytest.mark.asyncio
async def test_quiet_hours_and_proactive_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ScheduleStore(tmp_path / "q.db")
    store.set_prefs(
        NotificationPrefs(
            proactive_enabled=True,
            quiet_start_hour=22,
            quiet_end_hour=7,
        )
    )
    activity = ActivityTracker(store=store)
    activity.touch("default", at=0.0)
    hb = HeartbeatLoop(
        activity,
        policy=OutreachPolicy(idle_seconds=10, cooldown_seconds=1, max_per_day=3),
        open_topic_checker=lambda _sid: True,
        store=store,
    )
    monkeypatch.setattr(
        "fae.scheduler.heartbeat.in_quiet_hours",
        lambda *_a, **_k: True,
    )
    assert await hb.tick(now=100.0) == []

    monkeypatch.setattr(
        "fae.scheduler.heartbeat.in_quiet_hours",
        lambda *_a, **_k: False,
    )
    store.set_prefs(
        NotificationPrefs(
            proactive_enabled=False,
            quiet_start_hour=None,
            quiet_end_hour=None,
        )
    )
    assert await hb.tick(now=200.0) == []
    store.close()
