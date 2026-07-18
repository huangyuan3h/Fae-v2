"""Tests for create_memory_client factory."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.config import Settings
from fae.memory.factory import create_memory_client


@pytest.mark.asyncio
async def test_factory_off() -> None:
    client = await create_memory_client(Settings(letta_mode="off"))
    assert client is None


@pytest.mark.asyncio
async def test_factory_embedded(tmp_path: Path) -> None:
    settings = Settings(
        letta_mode="embedded",
        letta_embedded_path=str(tmp_path / "f.db"),
        letta_agent_name="fae-main",
    )
    client = await create_memory_client(settings)
    assert client is not None
    assert client.agent_id is not None
    await client.close()


@pytest.mark.asyncio
async def test_factory_remote_unreachable() -> None:
    settings = Settings(
        letta_mode="remote",
        letta_server_url="http://127.0.0.1:1",
    )
    client = await create_memory_client(settings)
    assert client is None
