"""Proactive LLM failure must notify (not silent canned-only)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from fae.llm.types import LLMConfig
from fae.scheduler.activity import ActivityTracker
from fae.scheduler.delivery import NotificationDelivery
from fae.scheduler.hub import ConnectionHub
from fae.scheduler.loop import ProactiveLoop
from fae.scheduler.store import ScheduleStore


@pytest.mark.asyncio
async def test_generate_missing_key_alerts(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "g.db")
    delivery = NotificationDelivery(store, ConnectionHub())
    loop = ProactiveLoop(
        store=store,
        activity=ActivityTracker(),
        delivery=delivery,
        llm=MagicMock(),
        default_llm_config=LLMConfig(api_key="unused", model="m"),
    )
    text = await loop._generate_with_skill(
        skill_name="proactive_outreach",
        session_id="default",
        user_prompt="hi",
        fallback="fallback-hi",
    )
    assert text == "fallback-hi"
    inbox = store.list_inbox()
    assert any("未配置模型" in i.title or "主动生成" in i.title for i in inbox)
    store.close()


@pytest.mark.asyncio
async def test_generate_uses_prepare_and_memory(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "g2.db")
    delivery = NotificationDelivery(store, ConnectionHub())
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=MagicMock(content="Yuan，周末去公园吗？"))
    memory = MagicMock()
    memory.enabled = True
    memory.prepare_request = AsyncMock(side_effect=lambda req, session_id=None: req)
    memory.client = MagicMock()
    memory.client.get_block = AsyncMock(return_value="Name: Yuan")

    loop = ProactiveLoop(
        store=store,
        activity=ActivityTracker(),
        delivery=delivery,
        llm=llm,
        memory=memory,
        default_llm_config=LLMConfig(api_key="sk-test", model="m"),
    )
    text = await loop._generate_with_skill(
        skill_name="proactive_outreach",
        session_id="default",
        user_prompt="check in",
        fallback="fallback",
    )
    assert "Yuan" in text
    memory.prepare_request.assert_awaited()
    llm.chat.assert_awaited()
    store.close()
