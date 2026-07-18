"""Tests for remote LettaMemoryClient with httpx mock transport."""

from __future__ import annotations

import httpx
import pytest

from fae.memory.letta_client import LettaMemoryClient
from fae.memory.schemas import FactIn, UserProfile


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/v1/health"):
        return httpx.Response(200, json={"status": "ok"})
    if path.rstrip("/").endswith("/v1/agents") and request.method == "GET":
        return httpx.Response(200, json=[])
    if path.rstrip("/").endswith("/v1/agents") and request.method == "POST":
        return httpx.Response(200, json={"id": "agent-1", "name": "fae-main"})
    if "/core-memory/blocks/human" in path and request.method == "GET":
        return httpx.Response(200, json={"label": "human", "value": "Name: 小明"})
    if "/core-memory/blocks/current" in path and request.method == "GET":
        return httpx.Response(200, json={"label": "current", "value": ""})
    if "/core-memory/blocks/human" in path and request.method == "PATCH":
        return httpx.Response(200, json={"label": "human", "value": "ok"})
    if path.endswith("/archival-memory") and request.method == "POST":
        return httpx.Response(200, json={"id": "p1", "text": "fact"})
    if "archival-memory" in path and request.method == "GET":
        return httpx.Response(
            200,
            json=[{"id": "p1", "text": "User's name is 小明", "tags": ["name"]}],
        )
    return httpx.Response(404, json={"error": path})


@pytest.mark.asyncio
async def test_ensure_agent_create_and_recall() -> None:
    transport = httpx.MockTransport(_handler)
    client = LettaMemoryClient("http://letta.test", agent_name="fae-main")
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        base_url="http://letta.test",
        transport=transport,
        timeout=3.0,
    )

    assert await client.health() is True
    agent_id = await client.ensure_agent()
    assert agent_id == "agent-1"

    await client.update_user(UserProfile(display_name="小明"))
    fact = await client.save_fact(FactIn(content="User's name is 小明", tags=["name"]))
    assert fact.id == "p1"
    hits = await client.search("小明")
    assert hits and "小明" in hits[0].content
    prompt = await client.recall_for_prompt("我叫什么")
    assert "小明" in prompt
    await client.close()


@pytest.mark.asyncio
async def test_ensure_agent_finds_existing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.rstrip("/").endswith("/v1/agents") and request.method == "GET":
            return httpx.Response(
                200,
                json=[{"id": "existing", "name": "fae-main"}],
            )
        if request.url.path.endswith("/v1/health"):
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(500, json={"error": request.url.path})

    client = LettaMemoryClient("http://letta.test")
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        base_url="http://letta.test",
        transport=httpx.MockTransport(handler),
        timeout=3.0,
    )
    assert await client.ensure_agent() == "existing"
    await client.close()
