"""Build a memory stack (client + recall + archival + compactor) from Settings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from fae.config import Settings
from fae.memory.archival import ArchivalBackend, create_archival
from fae.memory.compaction import MemoryCompactor
from fae.memory.embedded import EmbeddedMemoryClient
from fae.memory.letta_client import LettaMemoryClient
from fae.memory.protocol import MemoryClient
from fae.memory.recall_store import RecallStore

logger = logging.getLogger("fae.memory")

_REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass
class MemoryStack:
    """Wired memory dependencies for app.state / tests."""

    client: MemoryClient | None = None
    recall: RecallStore | None = None
    archival: ArchivalBackend | None = None
    compactor: MemoryCompactor | None = None

    async def close(self) -> None:
        client, self.client = self.client, None
        archival, self.archival = self.archival, None
        recall, self.recall = self.recall, None
        self.compactor = None
        if client is not None:
            closer = getattr(client, "_raw_close", client.close)
            try:
                await closer()
            except Exception:  # noqa: BLE001
                logger.exception("memory client.close failed")
        if archival is not None:
            try:
                await archival.close()
            except Exception:  # noqa: BLE001
                logger.exception("archival.close failed")
        if recall is not None:
            try:
                recall.close()
            except Exception:  # noqa: BLE001
                logger.exception("recall.close failed")


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


async def create_memory_stack(settings: Settings) -> MemoryStack:
    """Return a ready stack, or an empty stack if memory should stay disabled."""
    mode = (settings.letta_mode or "remote").strip().lower()
    agent_name = settings.letta_agent_name or "fae-main"
    char_limit = settings.core_current_char_limit

    if mode == "off":
        return MemoryStack()

    recall: RecallStore | None = None
    archival: ArchivalBackend | None = None
    client: MemoryClient | None = None
    try:
        recall = RecallStore(_resolve_path(settings.recall_db_path))
        archival = await create_archival(
            qdrant_url=settings.qdrant_url,
            prefer_stub=settings.archival_prefer_stub,
        )

        if mode == "embedded":
            db_path = _resolve_path(settings.letta_embedded_path)
            client = EmbeddedMemoryClient(
                db_path,
                agent_name=agent_name,
                recall_store=recall,
                current_char_limit=char_limit,
            )
            await client.ensure_agent()
            logger.info(
                "Memory mode=embedded path=%s agent=%s", db_path, agent_name
            )
        else:
            remote = LettaMemoryClient(
                settings.letta_server_url,
                agent_name=agent_name,
                api_key=settings.letta_server_password or None,
                timeout_s=3.0,
                recall_store=recall,
                current_char_limit=char_limit,
            )
            if not await remote.health():
                logger.warning(
                    "Letta unreachable at %s — memory disabled",
                    settings.letta_server_url,
                )
                await remote.close()
                await archival.close()
                recall.close()
                return MemoryStack()
            try:
                await remote.ensure_agent()
            except Exception:  # noqa: BLE001
                logger.exception("Letta ensure_agent failed — memory disabled")
                await remote.close()
                await archival.close()
                recall.close()
                return MemoryStack()
            client = remote
            logger.info(
                "Memory mode=remote url=%s agent=%s",
                settings.letta_server_url,
                agent_name,
            )

        compactor = MemoryCompactor(
            recall,
            archival,
            max_turns=settings.recall_max_turns,
            batch=settings.recall_compact_batch,
            client=client,
            current_char_limit=char_limit,
        )
        return MemoryStack(
            client=client,
            recall=recall,
            archival=archival,
            compactor=compactor,
        )
    except Exception:
        partial = MemoryStack(client=client, recall=recall, archival=archival)
        await partial.close()
        raise


async def create_memory_client(settings: Settings) -> MemoryClient | None:
    """Backward-compatible helper — prefer create_memory_stack in app code.

    ``client.close()`` also closes recall + archival owned by the stack.
    """
    stack = await create_memory_stack(settings)
    if stack.client is None:
        return None
    client = stack.client
    setattr(client, "_memory_stack", stack)
    setattr(client, "_raw_close", client.close)

    async def close_with_stack() -> None:
        await stack.close()

    client.close = close_with_stack  # type: ignore[method-assign]
    return client
