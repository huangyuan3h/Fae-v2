"""Tests for create_memory_stack factory."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.config import Settings
from fae.memory.factory import create_memory_client, create_memory_stack


@pytest.mark.asyncio
async def test_factory_off() -> None:
    stack = await create_memory_stack(Settings(letta_mode="off"))
    assert stack.client is None
    assert stack.recall is None


@pytest.mark.asyncio
async def test_factory_embedded(tmp_path: Path) -> None:
    settings = Settings(
        letta_mode="embedded",
        letta_embedded_path=str(tmp_path / "f.db"),
        recall_db_path=str(tmp_path / "recall.db"),
        letta_agent_name="fae-main",
        archival_prefer_stub=True,
    )
    stack = await create_memory_stack(settings)
    assert stack.client is not None
    assert stack.client.agent_id is not None
    assert stack.recall is not None
    assert stack.archival is not None
    assert stack.compactor is not None
    await stack.close()


@pytest.mark.asyncio
async def test_factory_remote_unreachable() -> None:
    settings = Settings(
        letta_mode="remote",
        letta_server_url="http://127.0.0.1:1",
        archival_prefer_stub=True,
    )
    stack = await create_memory_stack(settings)
    assert stack.client is None


@pytest.mark.asyncio
async def test_create_memory_client_compat(tmp_path: Path) -> None:
    settings = Settings(
        letta_mode="embedded",
        letta_embedded_path=str(tmp_path / "c.db"),
        recall_db_path=str(tmp_path / "r.db"),
        archival_prefer_stub=True,
    )
    client = await create_memory_client(settings)
    assert client is not None
    # close() must release recall + archival via the owned stack.
    await client.close()
