"""Phase 2.4 — sleeptime consolidation + idle scheduler."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae.api import create_app
from fae.config import Settings
from fae.llm import FakeProvider, LLMClient
from fae.memory.archival import StubArchival
from fae.memory.compaction import MemoryCompactor
from fae.memory.consolidation import MemoryConsolidator, SleeptimeScheduler
from memory_helpers import make_embedded


@pytest.mark.asyncio
async def test_consolidate_updates_current_and_facts(tmp_path: Path) -> None:
    client, recall, _ = make_embedded(tmp_path, name="sl.db")
    await client.ensure_agent()
    archival = StubArchival()
    recall.append("s", "我喜欢喝手冲咖啡", "记下了")
    recall.append("s", "今天天气不错", "是啊")
    consolidator = MemoryConsolidator(
        client,
        recall,
        archival=archival,
        current_char_limit=2000,
        max_runtime_s=5,
    )
    result = await consolidator.consolidate("s")
    assert result.skipped is None
    assert result.summarized_turns == 2
    assert result.current_updated is True
    assert result.facts_saved >= 1
    current = await client.get_block("current")
    assert "sleeptime" in current
    assert "咖啡" in current
    hits = await archival.search("咖啡", session_id="s")
    # Only upsert archival when turns > recent_keep (default 6); 2 turns skip.
    assert hits == [] or "咖啡" in (hits[0].content if hits else "")
    await client.close()
    recall.close()


@pytest.mark.asyncio
async def test_consolidate_writes_archival_when_many_turns(tmp_path: Path) -> None:
    client, recall, _ = make_embedded(tmp_path, name="sl2.db")
    await client.ensure_agent()
    archival = StubArchival()
    for i in range(8):
        recall.append("s", f"话题 {i} 喜欢爬山", f"ok{i}")
    consolidator = MemoryConsolidator(
        client,
        recall,
        archival=archival,
        recent_keep=6,
    )
    result = await consolidator.consolidate("s")
    assert result.summarized_turns == 8
    hits = await archival.search("爬山", top_k=5, session_id="s")
    assert hits and "sleeptime" in hits[0].content
    await client.close()
    recall.close()


@pytest.mark.asyncio
async def test_scheduler_idle_tick(tmp_path: Path) -> None:
    client, recall, _ = make_embedded(tmp_path, name="idle.db")
    await client.ensure_agent()
    recall.append("idle-s", "我喜欢 Rust", "好")
    consolidator = MemoryConsolidator(client, recall, max_runtime_s=5)
    scheduler = SleeptimeScheduler(
        consolidator,
        idle_seconds=1,
        poll_seconds=1,
        min_interval_s=0,
        daily_hour=None,
    )
    scheduler.touch("idle-s")
    # Pretend activity was in the past.
    scheduler._last_activity["idle-s"] = time.time() - 10
    results = await scheduler.tick()
    assert results and results[0].current_updated
    current = await client.get_block("current")
    assert "Rust" in current
    await client.close()
    recall.close()


@pytest.mark.asyncio
async def test_scheduler_min_interval(tmp_path: Path) -> None:
    client, recall, _ = make_embedded(tmp_path, name="int.db")
    await client.ensure_agent()
    recall.append("s", "喜欢茶", "嗯")
    consolidator = MemoryConsolidator(client, recall)
    scheduler = SleeptimeScheduler(
        consolidator,
        idle_seconds=1,
        min_interval_s=3600,
        daily_hour=None,
    )
    first = await scheduler.consolidate_now("s")
    assert first.skipped is None
    second = await scheduler.consolidate_now("s")
    assert second.skipped == "min_interval"
    await client.close()
    recall.close()


@pytest.mark.asyncio
async def test_consolidate_with_compactor(tmp_path: Path) -> None:
    client, recall, _ = make_embedded(tmp_path, name="cmp.db")
    await client.ensure_agent()
    archival = StubArchival()
    for i in range(6):
        recall.append("s", f"u{i}", f"a{i}")
    compactor = MemoryCompactor(
        recall, archival, max_turns=3, batch=2, client=client
    )
    consolidator = MemoryConsolidator(
        client, recall, archival=archival, compactor=compactor, recent_keep=2
    )
    result = await consolidator.consolidate("s")
    assert result.compacted >= 2
    assert recall.count_hot("s") <= 3
    await client.close()
    recall.close()


def test_consolidate_api(tmp_path: Path) -> None:
    settings = Settings(
        letta_mode="embedded",
        letta_embedded_path=str(tmp_path / "api.db"),
        recall_db_path=str(tmp_path / "api-recall.db"),
        archival_prefer_stub=True,
        sleeptime_enabled=True,
        sleeptime_daily_hour=None,
        sleeptime_min_interval_s=0,
    )
    app = create_app(
        settings=settings,
        llm_client=LLMClient(provider=FakeProvider(tokens=["x"])),
    )
    with TestClient(app) as http:
        http.post(
            "/api/chat",
            json={
                "config": {
                    "base_url": "http://x",
                    "api_key": "k",
                    "model": "m",
                },
                "messages": [{"role": "user", "content": "我喜欢喝美式"}],
                "session_id": "api-s",
            },
        )
        resp = http.post("/api/memory/consolidate?session_id=api-s")
        assert resp.status_code == 200
        body = resp.json()
        assert body["current_updated"] is True
        assert body["summarized_turns"] >= 1
        stats = http.get("/api/memory/stats").json()
        assert stats["sleeptime"] == "on"
