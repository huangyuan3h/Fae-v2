"""Regressions for Phase 4 review fixes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae import config as config_module
from fae.api import create_app
from fae.scheduler.activity import ActivityTracker
from fae.scheduler.loop import ProactiveLoop
from fae.scheduler.delivery import NotificationDelivery
from fae.scheduler.hub import ConnectionHub
from fae.scheduler.store import ScheduleStore


def test_builtins_present_when_scheduler_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("SCHEDULES_DB_PATH", str(tmp_path / "s.db"))
    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    jobs = {j["id"] for j in client.get("/api/schedules").json()["jobs"]}
    assert "daily_checkin" in jobs
    assert "weekly_recap" in jobs


def test_lifespan_restart_reopens_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("SCHEDULES_DB_PATH", str(tmp_path / "s.db"))
    config_module.get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c1:
        assert c1.get("/api/schedules").status_code == 200
    # Second lifespan on the same app must not use a closed SQLite handle.
    with TestClient(app) as c2:
        resp = c2.get("/api/schedules")
        assert resp.status_code == 200
        assert "jobs" in resp.json()


def test_open_topic_false_without_memory(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "s.db")
    activity = ActivityTracker()
    activity.touch("s1", at=0.0)
    loop = ProactiveLoop(
        store=store,
        activity=activity,
        delivery=NotificationDelivery(store, ConnectionHub()),
    )
    assert loop._has_open_topic("s1") is False
    store.close()


@pytest.mark.asyncio
async def test_date_job_claim_prevents_second_fire(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "s.db")
    delivery = NotificationDelivery(store, ConnectionHub())
    loop = ProactiveLoop(
        store=store,
        activity=ActivityTracker(),
        delivery=delivery,
    )
    job = store.create_custom_job(
        kind="date", title="once", body="once", run_at=1.0
    )
    r1 = await loop.run_job(job.id)
    assert r1["ok"] is True
    # Already claimed/disabled — second call still notifies but job stays off.
    assert store.get_job(job.id).enabled is False  # type: ignore[union-attr]
    before = len(store.list_inbox())
    await loop._check_due_reminders()
    assert len(store.list_inbox()) == before
    store.close()
