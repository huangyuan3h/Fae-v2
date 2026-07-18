"""Unit tests for Daily memory seed / persist helpers (no live Daily)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.memory.embedded import EmbeddedMemoryClient
from fae.pipecat.memory_processor import (
    build_memory_turn_processor,
    persist_daily_turn,
    seed_daily_memory,
)
from fae.pipecat.services.letta_memory import LettaMemoryService


@pytest.mark.asyncio
async def test_seed_daily_memory_adds_system_message(tmp_path: Path) -> None:
    client = EmbeddedMemoryClient(tmp_path / "d.db")
    await client.ensure_agent()
    await client.append_recall("daily-1", "喜欢咖啡", "好的")
    service = LettaMemoryService(client)
    messages: list[dict] = []

    text = await seed_daily_memory(
        memory=service,
        session_id="daily-1",
        add_message=messages.append,
    )
    assert "咖啡" in text
    assert messages and messages[0]["role"] == "system"
    assert "<fae_memory>" in messages[0]["content"]
    await client.close()


@pytest.mark.asyncio
async def test_persist_daily_turn_writes_recall(tmp_path: Path) -> None:
    client = EmbeddedMemoryClient(tmp_path / "d2.db")
    await client.ensure_agent()
    service = LettaMemoryService(client)
    await persist_daily_turn(
        memory=service,
        session_id="d2",
        user_text="聊聊 Rust",
        assistant_text="可以",
    )
    turns = await client.list_recall("d2")
    assert turns and "Rust" in turns[0].user_text
    await client.close()


def test_build_memory_turn_processor_none_when_disabled() -> None:
    assert build_memory_turn_processor(None, "s") is None
    assert build_memory_turn_processor(LettaMemoryService(None), "s") is None


@pytest.mark.asyncio
async def test_build_memory_turn_processor_enabled(tmp_path: Path) -> None:
    client = EmbeddedMemoryClient(tmp_path / "d3.db")
    await client.ensure_agent()
    service = LettaMemoryService(client)
    proc = build_memory_turn_processor(service, "s3")
    assert proc is not None
    await client.close()
