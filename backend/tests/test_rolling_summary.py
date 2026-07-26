"""Tests for R2 LLM-driven rolling summary (fae.memory.summarizer)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fae.llm import FakeProvider, LLMClient
from fae.llm.types import ChatMessage, ChatRequest, ChatResponse, LLMConfig
from fae.memory.archival import StubArchival
from fae.memory.summarizer import (
    RollingSummarizer,
    _parse_summary_payload,
)


def _make_summary_provider(payload: dict[str, Any]) -> FakeProvider:
    text = json.dumps(payload)
    return FakeProvider(responses=[text])


def _stub_archival() -> StubArchival:
    return StubArchival()


def _build(
    tmp_path: Path,
    *,
    client_obj,
    recall_obj,
    archival,
    llm_responses,
    **kwargs,
) -> RollingSummarizer:
    provider = (
        FakeProvider(responses=llm_responses)
        if not isinstance(llm_responses, FakeProvider)
        else llm_responses
    )
    llm = LLMClient(provider)
    return RollingSummarizer(
        llm=llm,
        config=LLMConfig(api_key="k", model="m"),
        recall=recall_obj,
        client=client_obj,
        archival=archival,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_summarizer_no_op_below_threshold(tmp_path: Path) -> None:
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    provider = _make_summary_provider(
        {"summary": "x", "facts": [], "open_questions": []}
    )
    summarizer = _build(
        tmp_path,
        client_obj=client,
        recall_obj=recall,
        archival=None,
        llm_responses=provider,
        max_turns=30,
    )
    for i in range(4):
        await client.append_recall("default", f"u{i}", f"a{i}")
    result = await summarizer.maybe_summarize("default")
    assert result is None
    assert provider.calls == []
    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_summarizer_compresses_and_writes_current(tmp_path: Path) -> None:
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    archival = _stub_archival()
    payload = {
        "summary": "User asked about Python asyncio race conditions.",
        "facts": ["user debugs asyncio code", "prefers terse answers"],
        "open_questions": ["outcome of fix?"],
    }
    provider = _make_summary_provider(payload)
    summarizer = _build(
        tmp_path,
        client_obj=client,
        recall_obj=recall,
        archival=archival,
        llm_responses=provider,
        max_turns=8,
        max_chars=500,
        recent_keep=2,
    )
    long_q = "question " + ("x" * 30)
    long_a = "answer " + ("y" * 30)
    for i in range(10):
        await client.append_recall("default", long_q, long_a)

    result = await summarizer.maybe_summarize("default")
    assert result is not None
    assert result.skipped is None
    assert result.summarized_turns == 8
    assert result.kept_recent == 2
    assert result.summary_text == payload["summary"]
    assert result.facts == payload["facts"]
    assert result.open_questions == payload["open_questions"]

    sent: ChatRequest = provider.calls[0]
    assert "json" in sent.messages[0].content.lower()
    assert "transcript" in sent.messages[1].content.lower()

    block = await client.get_block("current")
    assert "Rolling summary" in block
    assert payload["summary"] in block

    # Archival mirror exists and is tagged for retrieval.
    assert any("rolling" in item[6] for item in archival._items)

    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_summarizer_promotes_extracted_facts(tmp_path: Path) -> None:
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    payload = {
        "summary": "x",
        "facts": ["user lives in 上海", "allergy: 香菜"],
        "open_questions": [],
    }
    provider = _make_summary_provider(payload)
    summarizer = _build(
        tmp_path,
        client_obj=client,
        recall_obj=recall,
        archival=None,
        llm_responses=provider,
        max_turns=2,
        max_chars=500,
        recent_keep=1,
    )
    long_turn = "x" * 100
    for i in range(6):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")
    result = await summarizer.maybe_summarize("default")
    assert result is not None
    facts = await client.list_facts(limit=50, query=None)
    contents = {f.content for f in facts}
    assert "user lives in 上海" in contents
    assert "allergy: 香菜" in contents
    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_summarizer_handles_non_json_response(tmp_path: Path) -> None:
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    summarizer = _build(
        tmp_path,
        client_obj=client,
        recall_obj=recall,
        archival=None,
        llm_responses=["This is prose, not JSON. Just compress the gist."],
        max_turns=2,
        max_chars=500,
        recent_keep=1,
    )
    long_turn = "x" * 100
    for i in range(6):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")
    result = await summarizer.maybe_summarize("default")
    assert result is not None
    assert result.skipped is None
    assert result.summary_text.startswith("This is prose")
    assert result.facts == []
    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_summarizer_handles_fenced_json(tmp_path: Path) -> None:
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    summarizer = _build(
        tmp_path,
        client_obj=client,
        recall_obj=recall,
        archival=None,
        llm_responses=[
            '```json\n{"summary": "fenced", "facts": ["a"], "open_questions": []}\n```',
        ],
        max_turns=2,
        max_chars=500,
        recent_keep=1,
    )
    long_turn = "x" * 100
    for i in range(6):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")
    result = await summarizer.maybe_summarize("default")
    assert result is not None
    assert result.summary_text == "fenced"
    assert result.facts == ["a"]
    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_summarizer_timeout_returns_skip(tmp_path: Path) -> None:
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()

    class _SlowProvider(FakeProvider):
        async def chat(self, request: ChatRequest) -> ChatResponse:
            import asyncio

            await asyncio.sleep(5.0)
            return await super().chat(request)

    provider = _SlowProvider(
        responses=[json.dumps({"summary": "x", "facts": [], "open_questions": []})],
    )
    llm = LLMClient(provider)
    summarizer = RollingSummarizer(
        llm=llm,
        config=LLMConfig(api_key="k", model="m"),
        recall=recall,
        client=client,
        max_turns=2,
        max_chars=500,
        recent_keep=1,
        timeout_s=0.1,
    )
    long_turn = "x" * 100
    for i in range(6):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")
    result = await summarizer.maybe_summarize("default")
    assert result is not None
    assert result.skipped == "timeout"
    assert result.summary_text == ""
    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_summarizer_truncates_long_transcripts(tmp_path: Path) -> None:
    """Head+tail truncation keeps the summarizer prompt bounded."""
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    provider = _make_summary_provider(
        {"summary": "ok", "facts": [], "open_questions": []},
    )
    summarizer = _build(
        tmp_path,
        client_obj=client,
        recall_obj=recall,
        archival=None,
        llm_responses=provider,
        max_turns=2,
        max_chars=500,
        recent_keep=1,
    )
    huge = "x" * 4000
    for i in range(8):
        await client.append_recall("default", f"q{i} {huge}", f"a{i} {huge}")
    result = await summarizer.maybe_summarize("default")
    assert result is not None
    sent = provider.calls[0]
    body = sent.messages[1].content
    assert "truncated" in body
    assert len(body) < 20_000
    recall.close()
    await client.close()


def test_parse_summary_payload_handles_invalid() -> None:
    assert _parse_summary_payload("") == {
        "summary": "", "facts": [], "open_questions": [],
    }
    assert _parse_summary_payload("not json at all")["summary"].startswith("not json")
    parsed = _parse_summary_payload(
        '{"summary": "s", "facts": ["x"], "open_questions": ["y"]}'
    )
    assert parsed["summary"] == "s"
    assert parsed["facts"] == ["x"]
    assert parsed["open_questions"] == ["y"]