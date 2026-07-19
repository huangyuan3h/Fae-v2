"""Phase 2.3 — RecallStore, compaction, archival inject, stats API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fae.api import create_app
from fae.config import Settings
from fae.llm import FakeProvider, LLMClient
from fae.llm.types import ChatMessage, ChatRequest, LLMConfig
from fae.memory.archival import StubArchival, stub_embed
from fae.memory.compaction import MemoryCompactor
from fae.memory.core_budget import estimate_tokens, truncate_current
from fae.memory.recall_store import RecallStore
from memory_helpers import make_embedded


def test_recall_store_hot_window(tmp_path: Path) -> None:
    store = RecallStore(tmp_path / "r.db")
    store.append("s", "u1", "a1")
    store.append("s", "u2", "a2")
    assert store.count_hot("s") == 2
    turns = store.list_hot("s", limit=1)
    assert len(turns) == 1
    assert turns[0].user_text == "u2"
    popped = store.pop_oldest_hot("s", 1)
    assert popped[0].user_text == "u1"
    assert store.count_hot("s") == 1
    store.close()


def test_stub_embed_deterministic() -> None:
    a = stub_embed("hello")
    b = stub_embed("hello")
    assert a == b
    assert len(a) == 64


@pytest.mark.asyncio
async def test_create_archival_prefer_stub() -> None:
    from fae.memory.archival import create_archival

    backend = await create_archival(
        qdrant_url="http://127.0.0.1:1", prefer_stub=True
    )
    assert await backend.health() == "stub"
    await backend.close()


@pytest.mark.asyncio
async def test_create_archival_falls_back_when_qdrant_down() -> None:
    from fae.memory.archival import create_archival

    backend = await create_archival(
        qdrant_url="http://127.0.0.1:1", prefer_stub=False
    )
    assert await backend.health() == "stub"
    await backend.close()


@pytest.mark.asyncio
async def test_qdrant_archival_http_flow() -> None:
    import httpx

    from fae.memory.archival import QdrantArchival

    state: dict = {"created": False, "points": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/collections"):
            return httpx.Response(200, json={"result": {"collections": []}})
        if path.endswith("/collections/fae_archival") and request.method == "GET":
            if not state["created"]:
                return httpx.Response(404, json={"status": {"error": "Not found"}})
            return httpx.Response(200, json={"result": {"status": "green"}})
        if path.endswith("/collections/fae_archival") and request.method == "PUT":
            state["created"] = True
            return httpx.Response(200, json={"result": True})
        if path.endswith("/points") and request.method == "PUT":
            import json

            body = json.loads(request.content)
            state["points"].extend(body.get("points") or [])
            return httpx.Response(200, json={"result": {"status": "ok"}})
        if path.endswith("/points/search") and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "id": "p1",
                            "payload": {
                                "text": "archived Python notes",
                                "session_id": "s1",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"error": path})

    backend = QdrantArchival("http://qdrant.test")
    await backend._http.aclose()
    backend._http = httpx.AsyncClient(
        base_url="http://qdrant.test",
        transport=httpx.MockTransport(handler),
        timeout=3.0,
    )
    assert await backend.health() == "ok"
    await backend.ensure_ready()
    pid = await backend.upsert(text="hello archival", session_id="s1")
    assert pid
    hits = await backend.search("Python", top_k=3)
    assert hits and "Python" in hits[0].content
    await backend.close()


@pytest.mark.asyncio
async def test_core_stats_without_client() -> None:
    from fae.memory.core_budget import core_stats_from_client

    stats = await core_stats_from_client(None)
    assert stats["total_chars"] == 0
    assert "persona" in stats["blocks"]


@pytest.mark.asyncio
async def test_compact_when_over_max_turns(tmp_path: Path) -> None:
    client, recall, service = make_embedded(
        tmp_path,
        name="c.db",
        max_turns=3,
        batch=2,
        with_compactor=True,
    )
    await client.ensure_agent()
    sid = "compact-s"
    await service.persist_turn(
        session_id=sid,
        user_text="早期话题：Python 微服务",
        assistant_text="收到",
    )
    for i in range(4):
        await service.persist_turn(
            session_id=sid,
            user_text=f"filler turn {i}",
            assistant_text="ok",
        )
    assert recall.count_hot(sid) <= 3
    assert service.archival is not None
    hits = await service.archival.search("Python 微服务", top_k=5)
    assert hits
    assert any("Python" in h.content for h in hits)
    # Early topic should still surface via archival merge
    ctx = await service.recall_context("Python 微服务", session_id=sid)
    assert "Python" in ctx
    await client.close()
    recall.close()


@pytest.mark.asyncio
async def test_archival_inject_into_facts(tmp_path: Path) -> None:
    client, recall, _ = make_embedded(tmp_path, name="a.db")
    await client.ensure_agent()
    archival = StubArchival()
    await archival.upsert(
        text="[archived] User talked about climbing Mount Fuji",
        session_id="s",
    )
    from fae.pipecat.services.letta_memory import LettaMemoryService

    service = LettaMemoryService(client, archival=archival)
    ctx = await service.recall_context("Mount Fuji", session_id="s")
    assert "[facts]" in ctx
    assert "Fuji" in ctx
    await client.close()
    recall.close()


@pytest.mark.asyncio
async def test_archival_search_scoped_by_session() -> None:
    archival = StubArchival()
    await archival.upsert(text="session A secret topic alpha", session_id="a")
    await archival.upsert(text="session B secret topic beta", session_id="b")
    hits_a = await archival.search("secret", top_k=10, session_id="a")
    assert hits_a and all(h.session_id == "a" for h in hits_a)
    assert all("beta" not in h.content for h in hits_a)


@pytest.mark.asyncio
async def test_compact_keeps_hot_when_archival_fails(tmp_path: Path) -> None:
    from fae.memory.compaction import MemoryCompactor
    from fae.memory.embedded import EmbeddedMemoryClient
    from fae.memory.recall_store import RecallStore

    class BoomArchival:
        mode = "stub"

        async def ensure_ready(self) -> None:
            return None

        async def upsert(self, **kwargs):  # noqa: ANN003
            raise RuntimeError("qdrant down")

        async def search(self, *args, **kwargs):  # noqa: ANN003
            return []

        async def health(self) -> str:
            return "down"

        async def close(self) -> None:
            return None

    recall = RecallStore(tmp_path / "fail.db")
    client = EmbeddedMemoryClient(
        tmp_path / "fail-client.db", recall_store=recall
    )
    await client.ensure_agent()
    for i in range(5):
        recall.append("s", f"u{i}", f"a{i}")
    before = recall.count_hot("s")
    compactor = MemoryCompactor(
        recall, BoomArchival(), max_turns=2, batch=2, client=client
    )
    n = await compactor.maybe_compact("s")
    assert n == 0
    assert recall.count_hot("s") == before
    await client.close()
    recall.close()


@pytest.mark.asyncio
async def test_compactor_updates_current_block(tmp_path: Path) -> None:
    client, recall, _ = make_embedded(tmp_path, name="cur.db")
    await client.ensure_agent()
    archival = StubArchival()
    for i in range(5):
        recall.append("s", f"user-{i}", f"asst-{i}")
    compactor = MemoryCompactor(
        recall,
        archival,
        max_turns=2,
        batch=3,
        client=client,
    )
    n = await compactor.maybe_compact("s")
    assert n == 3
    current = await client.get_block("current")
    assert "user-0" in current or "user-1" in current
    await client.close()
    recall.close()


def test_truncate_current_and_token_est() -> None:
    assert truncate_current("abcdefghij", char_limit=5) == "fghij"
    assert estimate_tokens("abcd") == 1


def test_memory_stats_endpoint(tmp_path: Path) -> None:
    settings = Settings(
        letta_mode="embedded",
        letta_embedded_path=str(tmp_path / "stats.db"),
        recall_db_path=str(tmp_path / "stats-recall.db"),
        archival_prefer_stub=True,
    )
    app = create_app(
        settings=settings,
        llm_client=LLMClient(provider=FakeProvider(tokens=["x"])),
    )
    with TestClient(app) as client:
        # Seed one turn via HTTP chat
        resp = client.post(
            "/api/chat",
            json={
                "config": {
                    "base_url": "http://x",
                    "api_key": "k",
                    "model": "m",
                },
                "messages": [{"role": "user", "content": "我叫小明"}],
                "session_id": "stats-s",
            },
        )
        assert resp.status_code == 200
        stats = client.get("/api/memory/stats")
        assert stats.status_code == 200
        body = stats.json()
        assert body["archival"] == "stub"
        assert body["recall_turns"] >= 1
        assert "blocks" in body["core"]
        assert body["core"]["blocks"]["human"]["chars"] >= 0


@pytest.mark.asyncio
async def test_prepare_request_with_compacted_topic(tmp_path: Path) -> None:
    client, recall, service = make_embedded(
        tmp_path,
        name="prep.db",
        max_turns=2,
        batch=2,
        with_compactor=True,
    )
    await client.ensure_agent()
    sid = "prep"
    await service.persist_turn(
        session_id=sid, user_text="喜欢喝手冲咖啡", assistant_text="记下了"
    )
    await service.persist_turn(
        session_id=sid, user_text="今天天气不错", assistant_text="是啊"
    )
    await service.persist_turn(
        session_id=sid, user_text="晚上吃什么", assistant_text="随便"
    )
    await service.persist_turn(
        session_id=sid, user_text="再聊点别的", assistant_text="好"
    )
    req = ChatRequest(
        config=LLMConfig(api_key="k"),
        messages=[ChatMessage(role="user", content="我喜欢喝什么")],
    )
    prepared = await service.prepare_request(req, session_id=sid)
    text = prepared.messages[0].content
    assert "咖啡" in text
    await client.close()
    recall.close()
