"""Tightened open-topic eligibility (Phase Q.4.4)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from fae.memory.defaults import DEFAULT_HUMAN
from fae.memory.recall_store import RecallStore
from fae.scheduler.activity import ActivityTracker
from fae.scheduler.delivery import NotificationDelivery
from fae.scheduler.hub import ConnectionHub
from fae.scheduler.loop import ProactiveLoop
from fae.scheduler.store import ScheduleStore


@pytest.mark.asyncio
async def test_open_topic_false_for_arbitrary_episodic(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "s.db")
    episodic = MagicMock()
    episodic.list_events.return_value = [
        MagicMock(
            kind="note",
            summary="随便记了一笔",
            created_at=datetime.now(),
        )
    ]
    loop = ProactiveLoop(
        store=store,
        activity=ActivityTracker(),
        delivery=NotificationDelivery(store, ConnectionHub()),
        episodic=episodic,
    )
    assert await loop._has_open_topic("default") is False
    store.close()


@pytest.mark.asyncio
async def test_open_topic_true_for_personalized_human(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "s.db")
    memory = MagicMock()
    memory.enabled = True
    memory.client = MagicMock()
    memory.client.get_block = AsyncMock(return_value="Name: Yuan. Lives in Shanghai.")
    loop = ProactiveLoop(
        store=store,
        activity=ActivityTracker(),
        delivery=NotificationDelivery(store, ConnectionHub()),
        memory=memory,
    )
    assert await loop._has_open_topic("default") is True

    memory.client.get_block = AsyncMock(return_value=DEFAULT_HUMAN)
    assert await loop._has_open_topic("default") is False
    store.close()


@pytest.mark.asyncio
async def test_open_topic_true_for_hot_question(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "s.db")
    recall = RecallStore(tmp_path / "r.db")
    recall.append("default", "周末去哪玩？", "可以去公园")
    loop = ProactiveLoop(
        store=store,
        activity=ActivityTracker(),
        delivery=NotificationDelivery(store, ConnectionHub()),
        recall=recall,
    )
    assert await loop._has_open_topic("default") is True
    store.close()
    recall.close()
