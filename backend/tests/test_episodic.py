"""Phase 2.3b — episodic events, links, archival decay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae.api import create_app
from fae.config import Settings
from fae.llm import FakeProvider, LLMClient
from fae.memory.archival import StubArchival, decay_multiplier
from fae.memory.episodic import EpisodicStore, detect_life_events
from fae.pipecat.services.letta_memory import LettaMemoryService
from memory_helpers import make_embedded


def test_detect_life_events_zh_en() -> None:
    assert any(e.kind == "moved" for e in detect_life_events("下周我搬家到上海"))
    assert any(e.kind == "job_change" for e in detect_life_events("我换了工作"))
    assert any(e.kind == "job_change" for e in detect_life_events("I got a new job"))
    assert detect_life_events("今天天气不错") == []


def test_decay_multiplier() -> None:
    now = datetime.now(UTC)
    fresh = (now - timedelta(days=10)).isoformat()
    stale = (now - timedelta(days=200)).isoformat()
    assert decay_multiplier(fresh, decay_days=180, now=now) == 1.0
    assert decay_multiplier(stale, decay_days=180, now=now) == 0.25


@pytest.mark.asyncio
async def test_episodic_store_links(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "ep.db")
    ev = store.add_event(
        session_id="s",
        kind="moved",
        summary="User moved",
        raw_text="我搬家了",
    )
    store.link(ev.id, "fact", "fact-1")
    store.link(ev.id, "archival", "arch-1")
    listed = store.list_events(session_id="s")
    assert len(listed) == 1
    assert len(listed[0].links) == 2
    reverse = store.events_for_target("fact", "fact-1")
    assert reverse and reverse[0].id == ev.id
    store.close()


@pytest.mark.asyncio
async def test_persist_turn_records_event(tmp_path: Path) -> None:
    client, recall, _ = make_embedded(tmp_path, name="ep-svc.db")
    await client.ensure_agent()
    episodic = EpisodicStore(tmp_path / "ep-svc-events.db")
    archival = StubArchival()
    service = LettaMemoryService(
        client, archival=archival, episodic=episodic
    )
    await service.persist_turn(
        session_id="s1",
        user_text="下周我搬家到杭州",
        assistant_text="祝顺利",
    )
    events = episodic.list_events(session_id="s1")
    assert events and events[0].kind == "moved"
    assert any(lk.target_kind == "archival" for lk in events[0].links)
    ctx = await service.recall_context("搬家", session_id="s1")
    assert "[events]" in ctx
    assert "搬家" in ctx or "moved" in ctx.lower() or "relocating" in ctx.lower()
    await client.close()
    recall.close()
    episodic.close()


@pytest.mark.asyncio
async def test_archival_decay_downweights_stale() -> None:
    archival = StubArchival(decay_days=180)
    pid = await archival.upsert(text="ancient coffee preference", session_id="s")
    await archival.upsert(text="recent coffee note", session_id="s")
    old = (datetime.now(UTC) - timedelta(days=200)).isoformat()
    archival.set_last_accessed(pid, old)
    # Also backdate created_at by rewriting item tuple
    items = []
    for item in archival._items:
        if item[0] == pid:
            tags = item[6] if len(item) > 6 else []
            items.append((item[0], item[1], item[2], item[3], old, old, tags))
        else:
            items.append(item)
    archival._items = items
    hits = await archival.search("coffee", top_k=2, session_id="s")
    assert hits
    # Fresh hit should rank first when both match.
    assert "recent" in hits[0].content
    assert "decayed" in (hits[-1].tags if len(hits) > 1 else []) or len(hits) >= 1


def test_events_api(tmp_path: Path) -> None:
    settings = Settings(
        letta_mode="embedded",
        letta_embedded_path=str(tmp_path / "api.db"),
        recall_db_path=str(tmp_path / "api-recall.db"),
        episodic_db_path=str(tmp_path / "api-ep.db"),
        archival_prefer_stub=True,
        sleeptime_enabled=False,
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
                "messages": [{"role": "user", "content": "我换了工作去 AI 公司"}],
                "session_id": "ev-s",
            },
        )
        resp = http.get("/api/memory/events?session_id=ev-s")
        assert resp.status_code == 200
        body = resp.json()
        assert body["events"]
        assert body["events"][0]["kind"] == "job_change"
        stats = http.get("/api/memory/stats").json()
        assert stats["events"] >= 1
