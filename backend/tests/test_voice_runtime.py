"""Tests for VoiceRuntime registry + barge-in."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from fae.api import create_app
from fae.voice_runtime import VoiceRuntime


@pytest.mark.asyncio
async def test_interrupt_unknown_session() -> None:
    runtime = VoiceRuntime()
    assert await runtime.interrupt("missing") is False


@pytest.mark.asyncio
async def test_interrupt_calls_pipeline_hook() -> None:
    runtime = VoiceRuntime()
    handle = runtime.register("s1")
    called: list[bool] = []

    async def _interrupt() -> None:
        called.append(True)

    handle.interrupt_pipeline = _interrupt
    assert await runtime.interrupt("s1") is True
    assert called == [True]
    assert handle.barge_in.interrupted is True


@pytest.mark.asyncio
async def test_spawn_and_shutdown_cancels_task() -> None:
    runtime = VoiceRuntime()
    started = asyncio.Event()

    async def _long() -> None:
        started.set()
        await asyncio.sleep(60)

    runtime.register("s1")
    task = runtime.spawn("s1", _long())
    await started.wait()
    await runtime.shutdown()
    assert task.cancelled() or task.done()


def test_barge_in_with_registered_session() -> None:
    app = create_app()
    client = TestClient(app)
    session = client.post("/api/voice/session", json={}).json()
    sid = session["sessionId"]
    resp = client.post("/api/voice/barge-in", json={"session_id": sid})
    assert resp.status_code == 200
    assert resp.json()["action"] == "interrupted"


def test_memory_schemas_importable() -> None:
    from fae.memory import FactIn, FactOut, UserProfile
    from fae.memory.letta_client import LettaMemoryClient, memory_tool_stubs
    from fae.pipecat.services.letta_memory import LettaMemoryService

    fact = FactIn(content="likes coffee")
    assert fact.content
    assert FactOut(id="1", content="x")
    assert UserProfile(display_name="Ming")
    client = LettaMemoryClient("http://localhost:8283")
    assert client.agent_name == "fae-main"
    assert len(memory_tool_stubs()) == 3
    assert LettaMemoryService(None).enabled is False
