"""Extra Phase 4 coverage: NL parse branches, tools, hub, delivery, loop."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from fae.notifications.webpush import send_web_push
from fae.scheduler.delivery import NotificationDelivery, _in_quiet_hours
from fae.scheduler.hub import ConnectionHub
from fae.scheduler.loop import ProactiveLoop
from fae.scheduler.parse_nl import parse_schedule_text
from fae.scheduler.store import NotificationPrefs, ScheduleStore
from fae.scheduler.tools import (
    create_job_from_text,
    dispatch_schedule_tool,
    tool_cancel_job,
    tool_list_jobs,
)


def test_parse_nl_variants() -> None:
    now = datetime(2026, 7, 19, 10, 0, 0)
    assert parse_schedule_text("0 8 * * *").kind == "cron"
    assert parse_schedule_text("每天 8:30 喝水", now=now).cron == "30 8 * * *"
    assert parse_schedule_text("every day at 9am", now=now).cron == "0 9 * * *"
    assert parse_schedule_text("tomorrow at 3pm", now=now).kind == "date"
    assert parse_schedule_text("今天下午3点开会", now=now).kind == "date"
    assert parse_schedule_text("today at 4:00pm", now=now).kind == "date"
    assert parse_schedule_text("5分钟后提醒", now=now).kind == "date"
    assert parse_schedule_text("in 10 minutes", now=now).kind == "date"
    assert parse_schedule_text("15:30 提醒开会", now=now).kind == "date"
    with pytest.raises(ValueError):
        parse_schedule_text("")
    with pytest.raises(ValueError):
        parse_schedule_text("随便聊聊")


def test_tools_dispatch(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "t.db")
    job = create_job_from_text(store, "每天9点喝水")
    assert job.kind == "cron"
    listed = tool_list_jobs(store)
    assert any(j["id"] == job.id for j in listed)
    out = dispatch_schedule_tool(
        store, "schedule_create_job", '{"text":"明天10点吃药"}'
    )
    assert "ok" in out
    out2 = dispatch_schedule_tool(store, "list_jobs", "{}")
    assert "jobs" in out2
    assert tool_cancel_job(store, job.id)["ok"] is True
    # builtin disable path
    store.ensure_builtin_jobs(
        [("daily_checkin", "cron", "0 8 * * *", "Daily", {"skill": "daily_check_in"})]
    )
    assert tool_cancel_job(store, "daily_checkin")["disabled"] is True
    assert "unknown" in dispatch_schedule_tool(store, "nope", {})
    store.close()


@pytest.mark.asyncio
async def test_hub_broadcast_and_delivery_quiet(tmp_path: Path) -> None:
    hub = ConnectionHub()
    assert hub.active_count() == 0
    assert hub.sessions() == []

    class FakeWs:
        client_state = MagicMock()
        def __init__(self) -> None:
            from starlette.websockets import WebSocketState

            self.client_state = WebSocketState.CONNECTED
            self.sent: list = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    ws = FakeWs()
    hub.register(ws, "sess-a")  # type: ignore[arg-type]
    hub.update_session(ws, "sess-b")  # type: ignore[arg-type]
    n = await hub.broadcast({"type": "notification", "title": "t", "body": "b"})
    assert n == 1
    assert ws.sent
    hub.unregister(ws)  # type: ignore[arg-type]

    store = ScheduleStore(tmp_path / "d.db")
    store.set_prefs(
        NotificationPrefs(
            enabled=True,
            quiet_start_hour=0,
            quiet_end_hour=23,
            desktop_enabled=True,
            web_push_enabled=True,
        )
    )
    delivery = NotificationDelivery(store, ConnectionHub())
    item = await delivery.notify("t", "b", source="test")
    assert item.id
    # quiet → still in inbox
    assert store.list_inbox()
    store.close()


def test_webpush_skips_without_key() -> None:
    assert send_web_push(
        subscription={"endpoint": "x", "keys": {"p256dh": "a", "auth": "b"}},
        payload={"title": "t"},
        vapid_private_key="",
        vapid_claims={"sub": "mailto:t@t"},
    ) is False


@pytest.mark.asyncio
async def test_loop_daily_weekly_and_due(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "l.db")
    delivery = NotificationDelivery(store, ConnectionHub())
    episodic = MagicMock()
    episodic.list_events.return_value = [
        MagicMock(kind="note", summary="昨天做了 A", created_at=datetime.now())
    ]
    sleeptime = MagicMock()
    sleeptime.consolidate_now = AsyncMock()

    loop = ProactiveLoop(
        store=store,
        activity=MagicMock(),
        delivery=delivery,
        episodic=episodic,
        sleeptime=sleeptime,
        heartbeat_seconds=60,
    )
    await loop.start()
    r1 = await loop.run_job("daily_checkin")
    assert r1["ok"]
    r2 = await loop.run_job("weekly_recap")
    assert r2["ok"]
    sleeptime.consolidate_now.assert_awaited()

    # past due one-shot via heartbeat due check
    job = store.create_custom_job(
        kind="date", title="due", body="now", run_at=1.0
    )
    await loop._check_due_reminders()
    assert store.get_job(job.id) is not None
    assert store.list_inbox()
    await loop.stop()
    store.close()


def test_in_quiet_equal_hours() -> None:
    assert not _in_quiet_hours(5, 5, now_hour=5)


def test_store_mark_read_and_patch(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "m.db")
    item = store.add_inbox("a", "b")
    assert store.mark_read([item.id]) == 1
    assert store.mark_read() == 0
    job = store.create_custom_job(kind="cron", title="t", cron="0 1 * * *")
    patched = store.patch_job(
        job.id, title="t2", body="b2", cron="0 2 * * *", meta={"x": 1}
    )
    assert patched is not None
    assert patched.title == "t2"
    assert store.patch_job("missing") is None
    store.close()
