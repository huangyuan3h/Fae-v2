"""Compact hot recall turns into archival when over the window limit.

Lifecycle ordering
-----------------

``MemoryCompactor`` is the **raw fallback** of the rolling summary
lifecycle. ``RollingSummarizer`` runs first; when it successfully
commits a summary batch it claims ownership of the source turns by
writing ``recall_turns.summary_batch_id``. The compactor then **skips**
any turn that has ``summary_batch_id IS NOT NULL`` so the same turn is
never raw-archived twice (once by the summarizer's archival mirror,
once by the compactor).

If the summarizer was unavailable or its batch commit failed, the
uncovered turns flow through to the compactor as before, so behaviour
degrades gracefully.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fae.memory.archival import ArchivalBackend
    from fae.memory.protocol import MemoryClient
    from fae.memory.recall_store import RecallStore

logger = logging.getLogger("fae.memory.compaction")

# Safety cap so a pathological overflow cannot loop forever in one call.
_MAX_COMPACT_ROUNDS = 32


class MemoryCompactor:
    def __init__(
        self,
        recall: RecallStore,
        archival: ArchivalBackend,
        *,
        max_turns: int = 30,
        batch: int = 10,
        client: MemoryClient | None = None,
        current_char_limit: int = 2000,
    ) -> None:
        self.recall = recall
        self.archival = archival
        self.max_turns = max(2, max_turns)
        self.batch = max(1, batch)
        self.client = client
        self.current_char_limit = current_char_limit
        self._session_locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    async def maybe_compact(self, session_id: str) -> int:
        """Archive oldest *uncovered* turns if hot count exceeds max.

        Turns already claimed by a committed summary batch
        (``summary_batch_id IS NOT NULL``) are skipped — they are
        semantically archived via the summarizer's archival mirror.

        Returns the count of turns actually archived by this call.
        Upserts to archival first; only then marks turns archived so a
        failed write does not drop conversation history. Per-session
        lock avoids duplicate archival from concurrent persist/sleeptime.
        """
        sid = (session_id or "").strip() or "default"
        async with self._lock_for(sid):
            return await self._compact_unlocked(sid)

    async def _compact_unlocked(self, sid: str) -> int:
        total = 0
        for _ in range(_MAX_COMPACT_ROUNDS):
            hot = self.recall.count_hot(sid)
            if hot <= self.max_turns:
                break
            overflow = hot - self.max_turns
            n = min(self.batch, overflow)
            turns = self.recall.peek_oldest_uncovered(sid, n)
            if not turns:
                # Nothing left to claim (everything is covered by summaries).
                break
            # Re-check ids still hot (another path may have archived them).
            # Peek the full hot window so recently-appended uncovered turns
            # still pass the liveness check even when they're far from the
            # oldest end.
            still_hot = {
                t.id for t in self.recall.peek_oldest_hot(sid, max(hot, n))
            }
            turns = [t for t in turns if t.id in still_hot]
            if not turns:
                break
            summary_lines = [
                f"User: {t.user_text}\nAssistant: {t.assistant_text}" for t in turns
            ]
            summary = (
                f"[archived session={sid} turns={len(turns)}]\n"
                + "\n---\n".join(summary_lines)
            )
            try:
                await self.archival.upsert(text=summary, session_id=sid)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "archival upsert failed session=%s — keeping turns hot", sid
                )
                break
            self.recall.mark_archived([t.id for t in turns])
            await self._append_current_summary(sid, summary_lines[:3])
            total += len(turns)
            logger.info(
                "Compacted %s turns for session=%s (hot_now=%s)",
                len(turns),
                sid,
                self.recall.count_hot(sid),
            )
        return total

    async def _append_current_summary(
        self, session_id: str, lines: list[str]
    ) -> None:
        if self.client is None or not lines:
            return
        try:
            if not hasattr(self.client, "get_block") or not hasattr(
                self.client, "set_block"
            ):
                return
            current = await self.client.get_block("current")  # type: ignore[misc]
            note = f"[{session_id}] " + " | ".join(
                ln.replace("\n", " ")[:120] for ln in lines
            )
            merged = f"{(current or '').rstrip()}\n{note}".strip()
            if len(merged) > self.current_char_limit:
                merged = merged[-self.current_char_limit :]
            await self.client.set_block("current", merged)  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            logger.exception("failed to update current block after compact")
