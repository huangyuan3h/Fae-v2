"""Tests for the Rolling Summary lifecycle (P1 follow-up).

Covers:
- Same source-turn fingerprint across two ``maybe_summarize`` calls
  produces exactly one LLM call, one archival write, and one batch row.
- Subsequent call injects the previous batch's summary into the prompt.
- ``MemoryCompactor`` skips any turn whose ``summary_batch_id`` is set,
  so a summarized turn is never raw-archived twice.
- When the summarizer declines to commit (because the fingerprint is
  already committed), the compactor still runs on the uncovered
  overflow.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from fae.llm import FakeProvider, LLMClient
from fae.llm.types import ChatMessage, ChatRequest, ChatResponse, LLMConfig
from fae.memory.archival import StubArchival
from fae.memory.compaction import MemoryCompactor
from fae.memory.recall_store import RecallStore
from fae.memory.summarizer import RollingSummarizer


def _stub_archival() -> StubArchival:
    return StubArchival()


def _make_provider(payload: dict[str, Any]) -> FakeProvider:
    return FakeProvider(responses=[json.dumps(payload)])


def _build_summarizer(
    *,
    recall: RecallStore,
    client,
    archival,
    provider: FakeProvider,
    **kwargs,
) -> RollingSummarizer:
    return RollingSummarizer(
        llm=LLMClient(provider),
        config=LLMConfig(api_key="k", model="m"),
        recall=recall,
        client=client,
        archival=archival,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_summary_idempotent_for_same_hot_turns(tmp_path: Path) -> None:
    """Same hot window → exactly one LLM call, one batch, one archival row."""
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    archival = _stub_archival()
    payload = {
        "summary": "user debugging asyncio",
        "facts": ["prefers terse answers"],
        "open_questions": [],
    }
    provider = _make_provider(payload)
    summarizer = _build_summarizer(
        recall=recall,
        client=client,
        archival=archival,
        provider=provider,
        max_turns=4,
        max_chars=300,
        recent_keep=1,
    )
    long_turn = "x" * 80
    for i in range(8):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")

    first = await summarizer.maybe_summarize("default")
    assert first is not None
    assert first.skipped is None
    assert first.batch_id is not None
    assert first.archive_point_id == first.batch_id
    assert len(provider.calls) == 1

    archival_after_first = len(archival._items)
    assert archival_after_first == 1
    batches_after_first = len(
        recall._conn.execute(
            "SELECT batch_id FROM recall_summary_batches WHERE session_id='default'"
        ).fetchall()
    )
    assert batches_after_first == 1

    second = await summarizer.maybe_summarize("default")
    assert second is not None
    assert second.skipped == "already_committed"
    assert second.batch_id == first.batch_id
    assert len(provider.calls) == 1
    assert len(archival._items) == archival_after_first
    batches_after_second = len(
        recall._conn.execute(
            "SELECT batch_id FROM recall_summary_batches WHERE session_id='default'"
        ).fetchall()
    )
    assert batches_after_second == 1

    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_summary_passes_previous_summary_to_next_round(tmp_path: Path) -> None:
    """Round 2 prompt contains round 1's summary as <previous_summary>."""
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    archival = _stub_archival()
    payload_first = {
        "summary": "DURABLE FACT: user lives in Shanghai",
        "facts": ["lives in Shanghai"],
        "open_questions": [],
    }
    payload_second = {
        "summary": "DURABLE FACT: user lives in Shanghai AND is debugging PG migration",
        "facts": ["lives in Shanghai", "debugging PG migration"],
        "open_questions": [],
    }
    provider = FakeProvider(responses=[json.dumps(payload_first), json.dumps(payload_second)])
    summarizer = _build_summarizer(
        recall=recall,
        client=client,
        archival=archival,
        provider=provider,
        max_turns=4,
        max_chars=300,
        recent_keep=1,
    )
    long_turn = "x" * 80
    for i in range(8):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")

    first = await summarizer.maybe_summarize("default")
    assert first is not None
    assert first.skipped is None
    assert first.summary_text == payload_first["summary"]

    # Add two more turns to push past max_turns again with new uncovered turns.
    for i in range(8, 10):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")

    second = await summarizer.maybe_summarize("default")
    assert second is not None
    assert second.skipped is None
    assert second.summary_text == payload_second["summary"]
    assert second.batch_id and second.batch_id != first.batch_id

    assert len(provider.calls) == 2
    second_prompt = provider.calls[1].messages[1].content
    assert "<previous_summary>" in second_prompt
    assert "DURABLE FACT: user lives in Shanghai" in second_prompt

    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_compactor_skips_already_summarized_turns(tmp_path: Path) -> None:
    """Compactor raw-archival must skip any turn the summarizer claimed."""
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    archival = _stub_archival()
    payload = {
        "summary": "s",
        "facts": [],
        "open_questions": [],
    }
    provider = _make_provider(payload)
    summarizer = _build_summarizer(
        recall=recall,
        client=client,
        archival=archival,
        provider=provider,
        max_turns=4,
        max_chars=300,
        recent_keep=1,
    )
    compactor = MemoryCompactor(
        recall=recall,
        archival=archival,
        max_turns=4,
        batch=4,
        client=client,
    )
    long_turn = "x" * 80
    for i in range(8):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")

    result = await summarizer.maybe_summarize("default")
    assert result is not None
    assert result.skipped is None
    summarized_turn_ids = {
        row["id"]
        for row in recall._conn.execute(
            "SELECT id FROM recall_turns WHERE summary_batch_id IS NOT NULL"
        ).fetchall()
    }
    assert len(summarized_turn_ids) == result.summarized_turns

    archival_after_summary = len(archival._items)
    archived = await compactor.maybe_compact("default")
    # Compactor should only touch uncovered turns (the recent_keep=1 turn).
    uncovered_archived = len(archival._items) - archival_after_summary
    assert uncovered_archived == archived
    assert uncovered_archived == 1

    # The summarized turn IDs must NOT appear in any raw archival block.
    raw_texts = "\n".join(item[1] for item in archival._items)
    for tid in summarized_turn_ids:
        assert tid not in raw_texts

    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_compactor_falls_back_for_unsummarized_overflow(tmp_path: Path) -> None:
    """If summarizer is unavailable, compactor must still raw-archive overflow."""
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    archival = _stub_archival()
    compactor = MemoryCompactor(
        recall=recall,
        archival=archival,
        max_turns=4,
        batch=10,
        client=client,
    )
    long_turn = "x" * 80
    for i in range(10):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")

    archived = await compactor.maybe_compact("default")
    assert archived == 10 - 4  # = 6 raw-archived
    assert len(archival._items) == 1

    covered = recall._conn.execute(
        "SELECT COUNT(*) AS n FROM recall_turns WHERE summary_batch_id IS NOT NULL"
    ).fetchone()["n"]
    assert covered == 0

    hot = recall.count_hot("default")
    assert hot == 4

    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_summary_fingerprint_changes_when_window_changes(tmp_path: Path) -> None:
    """A new turn entering the window produces a new fingerprint → new batch."""
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    archival = _stub_archival()
    provider = FakeProvider(
        responses=[
            json.dumps({"summary": "first", "facts": [], "open_questions": []}),
            json.dumps({"summary": "second", "facts": [], "open_questions": []}),
        ]
    )
    summarizer = _build_summarizer(
        recall=recall,
        client=client,
        archival=archival,
        provider=provider,
        max_turns=4,
        max_chars=300,
        recent_keep=1,
    )
    long_turn = "x" * 80
    for i in range(8):
        await client.append_recall("default", f"q{i} {long_turn}", f"a{i} {long_turn}")

    first = await summarizer.maybe_summarize("default")
    assert first is not None
    assert first.summary_text == "first"

    # Append another turn so the uncovered tail grows.
    await client.append_recall("default", f"q8 {long_turn}", f"a8 {long_turn}")
    second = await summarizer.maybe_summarize("default")
    assert second is not None
    assert second.skipped is None
    assert second.summary_text == "second"
    assert second.batch_id != first.batch_id

    recall.close()
    await client.close()


@pytest.mark.asyncio
async def test_commit_summary_batch_is_idempotent_at_store_layer(tmp_path: Path) -> None:
    """Re-committing the same fingerprint at the store layer is a no-op."""
    from memory_helpers import make_embedded

    client, recall, _service = make_embedded(tmp_path)
    await client.ensure_agent()
    for i in range(2):
        await client.append_recall("default", f"q{i}", f"a{i}")

    turns = recall.peek_oldest_uncovered("default", 2)
    fingerprint = RollingSummarizer._fingerprint_for("default", turns)

    first = recall.commit_summary_batch(
        session_id="default",
        fingerprint=fingerprint,
        turn_ids=[t.id for t in turns],
        summary_text="once",
        batch_id="batch-A",
    )
    assert first is not None and first["batch_id"] == "batch-A"

    second = recall.commit_summary_batch(
        session_id="default",
        fingerprint=fingerprint,
        turn_ids=[t.id for t in turns],
        summary_text="twice",
        batch_id="batch-B",
    )
    assert second is None  # uniqueness violation → no-op

    # Canonical summary_text is the first commit's.
    canonical = recall.latest_batch("default")
    assert canonical["summary_text"] == "once"
    assert canonical["batch_id"] == "batch-A"

    recall.close()
    await client.close()