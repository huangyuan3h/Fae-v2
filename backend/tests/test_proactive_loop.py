"""Phase 4 ProactiveLoop + delivery integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.agent.skills_runtime import SkillRuntime
from fae.llm import FakeProvider, LLMClient
from fae.scheduler.activity import ActivityTracker
from fae.scheduler.delivery import NotificationDelivery
from fae.scheduler.hub import ConnectionHub
from fae.scheduler.loop import ProactiveLoop
from fae.scheduler.proactive import OutreachPolicy
from fae.scheduler.store import ScheduleStore


@pytest.mark.asyncio
async def test_outreach_notifies(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "s.db")
    hub = ConnectionHub()
    delivery = NotificationDelivery(store, hub)
    activity = ActivityTracker()
    activity.touch("s1", at=0.0)

    skills = SkillRuntime(
        skills_dir=Path(__file__).resolve().parents[1] / "src" / "skills",
        state_path=tmp_path / "skills.json",
        repo_root=tmp_path,
    )
    loop = ProactiveLoop(
        store=store,
        activity=activity,
        delivery=delivery,
        skills=skills,
        llm=LLMClient(FakeProvider(responses=["嗨，最近怎么样？"])),
        heartbeat_seconds=30,
        outreach_idle_hours=0.001,  # ~3.6s → use tiny via policy override below
    )
    # Force policy for test
    loop.heartbeat.policy = OutreachPolicy(
        idle_seconds=10,
        cooldown_seconds=1,
        max_per_day=2,
    )
    loop.heartbeat.open_topic_checker = lambda _sid: True

    fired = await loop.heartbeat.tick(now=100.0)
    assert fired == ["s1"]
    inbox = store.list_inbox()
    assert inbox
    assert "嗨" in inbox[0].body or "想" in inbox[0].title
    store.close()


@pytest.mark.asyncio
async def test_run_custom_job_notifies(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "s.db")
    delivery = NotificationDelivery(store, ConnectionHub())
    activity = ActivityTracker()
    loop = ProactiveLoop(
        store=store,
        activity=activity,
        delivery=delivery,
        heartbeat_seconds=60,
    )
    job = store.create_custom_job(
        kind="date",
        title="吃维生素",
        body="记得吃维生素",
        run_at=1.0,
    )
    result = await loop.run_job(job.id)
    assert result["ok"] is True
    items = store.list_inbox()
    assert any("维生素" in i.body or "维生素" in i.title for i in items)
    store.close()


@pytest.mark.asyncio
async def test_proactive_start_registers_builtins(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "s.db")
    loop = ProactiveLoop(
        store=store,
        activity=ActivityTracker(),
        delivery=NotificationDelivery(store, ConnectionHub()),
        heartbeat_seconds=60,
    )
    await loop.start()
    ids = {j.id for j in store.list_jobs()}
    assert "daily_checkin" in ids
    assert "weekly_recap" in ids
    await loop.stop()
    store.close()
