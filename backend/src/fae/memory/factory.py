"""Build a memory client from Settings."""

from __future__ import annotations

import logging
from pathlib import Path

from fae.config import Settings
from fae.memory.embedded import EmbeddedMemoryClient
from fae.memory.letta_client import LettaMemoryClient
from fae.memory.protocol import MemoryClient

logger = logging.getLogger("fae.memory")

_REPO_ROOT = Path(__file__).resolve().parents[4]


async def create_memory_client(settings: Settings) -> MemoryClient | None:
    """Return a ready client, or None if memory should stay disabled."""
    mode = (settings.letta_mode or "remote").strip().lower()
    agent_name = settings.letta_agent_name or "fae-main"

    if mode == "off":
        return None

    if mode == "embedded":
        path = settings.letta_embedded_path
        db_path = Path(path) if path else _REPO_ROOT / ".data" / "fae-memory.db"
        if not db_path.is_absolute():
            db_path = _REPO_ROOT / db_path
        client: MemoryClient = EmbeddedMemoryClient(db_path, agent_name=agent_name)
        await client.ensure_agent()
        logger.info("Memory mode=embedded path=%s agent=%s", db_path, agent_name)
        return client

    # remote (default)
    client = LettaMemoryClient(
        settings.letta_server_url,
        agent_name=agent_name,
        api_key=settings.letta_server_password or None,
        timeout_s=3.0,
    )
    if not await client.health():
        logger.warning(
            "Letta unreachable at %s — memory disabled",
            settings.letta_server_url,
        )
        await client.close()
        return None
    try:
        await client.ensure_agent()
    except Exception:  # noqa: BLE001
        logger.exception("Letta ensure_agent failed — memory disabled")
        await client.close()
        return None
    logger.info(
        "Memory mode=remote url=%s agent=%s",
        settings.letta_server_url,
        agent_name,
    )
    return client
