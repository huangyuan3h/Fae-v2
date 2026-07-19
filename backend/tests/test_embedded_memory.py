"""Tests for EmbeddedMemoryClient + LettaMemoryService."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.llm.types import ChatMessage, ChatRequest, LLMConfig
from fae.memory.defaults import DEFAULT_PERSONA
from fae.memory.schemas import FactIn, UserProfile
from memory_helpers import make_embedded


@pytest.mark.asyncio
async def test_embedded_roundtrip(tmp_path: Path) -> None:
    client, _recall, _service = make_embedded(tmp_path, name="m.db")
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
    assert "[persona]" in prompt
    assert "warm bilingual companion" in prompt or DEFAULT_PERSONA[:40] in prompt

    await client.append_recall("s1", "我在做 Python 项目", "听起来不错")
    turns = await client.list_recall("s1", limit=5)
    assert len(turns) == 1
    assert "Python" in turns[0].user_text
    with_turns = await client.recall_for_prompt(
        "Python", session_id="s1", recent_limit=5
    )
    assert "[recent_turns]" in with_turns
    assert "Python" in with_turns
    await client.close()


@pytest.mark.asyncio
async def test_memory_service_inject_and_persist(tmp_path: Path) -> None:
    client, _recall, service = make_embedded(tmp_path, name="m2.db")
    await client.ensure_agent()

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
    assert "[persona]" in prepared.messages[0].content
    assert "小明" in prepared.messages[0].content

    custom = "You are FAE, speak with extreme warmth and remember birthdays."
    await client.set_block("persona", custom)
    prepared2 = await service.prepare_request(req, session_id="s")
    assert custom in prepared2.messages[0].content
    await client.close()
