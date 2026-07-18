"""Tests for EmbeddedMemoryClient + LettaMemoryService."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.memory.embedded import EmbeddedMemoryClient
from fae.memory.schemas import FactIn, UserProfile
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.llm.types import ChatMessage, ChatRequest, LLMConfig


@pytest.mark.asyncio
async def test_embedded_roundtrip(tmp_path: Path) -> None:
    client = EmbeddedMemoryClient(tmp_path / "m.db", agent_name="fae-main")
    await client.ensure_agent()
    assert client.agent_id

    await client.update_user(UserProfile(display_name="小明"))
    await client.save_fact(
        FactIn(content="User's name is 小明", tags=["name"], session_id="s")
    )
    hits = await client.search("小明", top_k=5)
    assert any("小明" in h.content for h in hits)

    prompt = await client.recall_for_prompt("我叫什么")
    assert "小明" in prompt
    await client.close()


@pytest.mark.asyncio
async def test_memory_service_inject_and_persist(tmp_path: Path) -> None:
    client = EmbeddedMemoryClient(tmp_path / "m2.db")
    await client.ensure_agent()
    service = LettaMemoryService(client)

    await service.persist_turn(
        session_id="s",
        user_text="我叫小明",
        assistant_text="好的，小明！",
    )
    req = ChatRequest(
        config=LLMConfig(api_key="k"),
        messages=[ChatMessage(role="user", content="我叫什么")],
    )
    prepared = await service.prepare_request(req, session_id="s")
    assert prepared.messages[0].role == "system"
    assert "<fae_memory>" in prepared.messages[0].content
    assert "小明" in prepared.messages[0].content
    await client.close()
