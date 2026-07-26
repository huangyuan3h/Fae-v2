"""Tests for R4 Letta-style reflection subagent (fae.memory.reflection)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fae.llm import FakeProvider, LLMClient
from fae.llm.types import ChatMessage, ChatRequest, ChatResponse, LLMConfig
from fae.memory.reflection import (
    ReflectionOutcome,
    SubagentReflectionRunner,
    _format_current_note,
    _parse_reflection_payload,
    _render_turns,
)


def _reflection_provider(payload: dict[str, Any]) -> FakeProvider:
    return FakeProvider(responses=[json.dumps(payload)])


@pytest.mark.asyncio
async def test_reflection_runner_writes_current_and_facts(tmp_path: Path) -> None:
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    payload = {
        "summary": "User lives in 上海, prefers 少油.",
        "facts": ["lives_in: 上海", "diet: 少油"],
        "open_questions": ["follow up on Python bug?"],
    }
    provider = _reflection_provider(payload)
    runner = SubagentReflectionRunner(
        llm=LLMClient(provider),
        config=LLMConfig(api_key="k", model="m"),
        max_task_chars=500,
        timeout_s=10.0,
        current_char_limit=600,
    )

    for i in range(3):
        await client.append_recall("default", f"q{i} " + ("x" * 50), f"a{i}")

    from fae.memory.consolidation import MemoryConsolidator

    consolidator = MemoryConsolidator(
        client,
        recall,
        current_char_limit=600,
        reflection_runner=runner,
    )
    result = await consolidator.consolidate("default")
    assert result.delegated is True
    assert result.skipped is None
    assert result.facts_saved >= 2
    assert result.current_updated is True

    # Current block carries the reflection summary.
    block = await client.get_block("current")
    assert "Reflection" in block
    assert payload["summary"] in block
    assert "follow up on Python bug?" in block

    # Reflection LLM was called with a strict-JSON prompt.
    sent = provider.calls[0]
    sys_msg = next(m for m in sent.messages if m.role == "system").content
    assert "JSON" in sys_msg
    user_msg = next(m for m in sent.messages if m.role == "user").content
    # Subagent wraps task text in "Task:\n..." — verify our transcript
    # was rendered in the prompt body.
    assert "Task:" in user_msg
    assert "[1] user:" in user_msg

    # Facts were saved through the client.
    facts = await client.list_facts(limit=50, query=None)
    contents = {f.content for f in facts}
    assert "lives_in: 上海" in contents
    assert "diet: 少油" in contents

    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_reflection_runner_skips_on_subagent_error(tmp_path: Path) -> None:
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    # Return an empty summary so the subagent path raises invalid_payload.
    provider = FakeProvider(responses=[""])
    runner = SubagentReflectionRunner(
        llm=LLMClient(provider),
        config=LLMConfig(api_key="k", model="m"),
        max_task_chars=200,
        timeout_s=10.0,
        current_char_limit=400,
    )
    from fae.memory.consolidation import MemoryConsolidator

    consolidator = MemoryConsolidator(
        client,
        recall,
        current_char_limit=400,
        reflection_runner=runner,
    )
    for i in range(3):
        await client.append_recall("default", f"q{i}", f"a{i}")
    # Empty LLM response → empty_response error → fallback to bullets.
    result = await consolidator.consolidate("default")
    assert result.delegated is True
    # Soft skip is swallowed so the scheduler treats the pass as
    # successful — the bullet summary still lands.
    assert result.skipped is None
    assert result.current_updated is True
    block = await client.get_block("current")
    assert block != ""
    assert "sleeptime" in block
    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_consolidator_falls_back_when_runner_returns_none(tmp_path: Path) -> None:
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()

    async def _bad_runner(session_id, turns, consolidator):  # noqa: ANN001
        return None

    from fae.memory.consolidation import MemoryConsolidator

    consolidator = MemoryConsolidator(
        client,
        recall,
        current_char_limit=400,
        reflection_runner=_bad_runner,
    )
    for i in range(3):
        await client.append_recall("default", f"q{i}", f"a{i}")
    result = await consolidator.consolidate("default")
    assert result.delegated is False
    assert result.current_updated is True
    block = await client.get_block("current")
    assert "sleeptime" in block
    recall.close()
    await client.close()


def test_render_turns_truncates_long_transcripts() -> None:
    long = "x" * 1000
    turns = [
        type("T", (), {"user_text": long, "assistant_text": long})() for _ in range(20)
    ]
    rendered = _render_turns(turns, max_chars=500)
    assert "truncated" in rendered
    assert len(rendered) < 1000


def test_parse_reflection_payload_handles_fences() -> None:
    raw = '```json\n{"summary": "x", "facts": ["a"], "open_questions": []}\n```'
    parsed = _parse_reflection_payload(raw)
    assert parsed is not None
    assert parsed["summary"] == "x"
    assert parsed["facts"] == ["a"]


def test_parse_reflection_payload_handles_invalid() -> None:
    assert _parse_reflection_payload("") is None
    assert _parse_reflection_payload("not json") is None
    # Empty payload is also None.
    assert _parse_reflection_payload('{"summary": "", "facts": [], "open_questions": []}') is None


def test_format_current_note_includes_open_questions() -> None:
    note = _format_current_note(
        "default", 5, "summary text", ["q1", "q2"],
    )
    assert "Reflection" in note
    assert "summary text" in note
    assert "- q1" in note
    assert "- q2" in note