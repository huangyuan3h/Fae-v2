"""Sleeptime memory consolidation (Phase 2.4).

Heuristic first cut: summarize hot recall into Core ``current``, promote
durable preference/identity lines to facts, then optionally compact.
No live LLM required so unit tests stay offline-friendly.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fae.memory.schemas import FactIn

if TYPE_CHECKING:
    from fae.memory.archival import ArchivalBackend
    from fae.memory.compaction import MemoryCompactor
    from fae.memory.protocol import MemoryClient
    from fae.memory.recall_store import RecallStore

logger = logging.getLogger("fae.memory.consolidation")

# Preference / durable-topic hints for fact promotion (zh + en).
_DURABLE_PATTERNS = (
    re.compile(r"(喜欢|爱喝|爱吃|讨厌|偏好|习惯)"),
    re.compile(r"(?i)\b(like|love|hate|prefer|favorite)\b"),
    re.compile(r"(我叫|我的名字|工作|搬家|住在)"),
    re.compile(r"(?i)\b(my name is|i work|i live|moved)\b"),
)


@dataclass
class ConsolidateResult:
    session_id: str
    summarized_turns: int = 0
    facts_saved: int = 0
    current_updated: bool = False
    compacted: int = 0
    skipped: str | None = None
    elapsed_s: float = 0.0


class MemoryConsolidator:
    """Summarize hot recall → core current + optional facts."""

    def __init__(
        self,
        client: MemoryClient,
        recall: RecallStore,
        *,
        archival: ArchivalBackend | None = None,
        compactor: MemoryCompactor | None = None,
        current_char_limit: int = 2000,
        max_runtime_s: float = 30.0,
        recent_keep: int = 6,
    ) -> None:
        self.client = client
        self.recall = recall
        self.archival = archival
        self.compactor = compactor
        self.current_char_limit = current_char_limit
        self.max_runtime_s = max(1.0, max_runtime_s)
        self.recent_keep = max(1, recent_keep)

    async def consolidate(self, session_id: str) -> ConsolidateResult:
        sid = (session_id or "").strip() or "default"
        started = time.monotonic()
        result = ConsolidateResult(session_id=sid)
        try:
            async with asyncio.timeout(self.max_runtime_s):
                await self._run(sid, result)
        except TimeoutError:
            result.skipped = "timeout"
            logger.warning("consolidate timeout session=%s", sid)
        except Exception:  # noqa: BLE001
            logger.exception("consolidate failed session=%s", sid)
            result.skipped = "error"
        result.elapsed_s = time.monotonic() - started
        return result

    async def _run(self, sid: str, result: ConsolidateResult) -> None:
        turns = self.recall.list_hot(sid, limit=200)
        if not turns:
            result.skipped = "empty"
            return

        # Keep the newest recent_keep in hot window narrative; summarize all.
        summary_lines = [
            f"User: {t.user_text} | Assistant: {t.assistant_text}" for t in turns
        ]
        bullets = "\n".join(f"- {ln[:200]}" for ln in summary_lines[-20:])
        note = f"[sleeptime session={sid} turns={len(turns)}]\n{bullets}"

        if hasattr(self.client, "get_block") and hasattr(self.client, "set_block"):
            current = await self.client.get_block("current")  # type: ignore[misc]
            merged = f"{(current or '').rstrip()}\n{note}".strip()
            if len(merged) > self.current_char_limit:
                merged = merged[-self.current_char_limit :]
            await self.client.set_block("current", merged)  # type: ignore[misc]
            result.current_updated = True

        result.summarized_turns = len(turns)
        result.facts_saved = await self._promote_facts(sid, turns)

        if self.archival is not None and len(turns) > self.recent_keep:
            # Persist a sleeptime passage for later recall injection.
            archival_text = (
                f"[sleeptime session={sid}]\n" + "\n".join(summary_lines[:10])
            )
            try:
                await self.archival.upsert(text=archival_text, session_id=sid)
            except Exception:  # noqa: BLE001
                logger.exception("sleeptime archival upsert failed session=%s", sid)

        if self.compactor is not None:
            result.compacted = await self.compactor.maybe_compact(sid)

    async def _promote_facts(self, sid: str, turns: list[Any]) -> int:
        saved = 0
        seen: set[str] = set()
        for turn in turns:
            text = (turn.user_text or "").strip()
            if not text or not _looks_durable(text):
                continue
            key = text[:120]
            if key in seen:
                continue
            seen.add(key)
            try:
                await self.client.save_fact(
                    FactIn(
                        content=f"User said: {key}",
                        tags=["sleeptime", "preference"],
                        session_id=sid,
                    )
                )
                saved += 1
            except Exception:  # noqa: BLE001
                logger.exception("save_fact during consolidate failed")
        return saved


def _looks_durable(text: str) -> bool:
    return any(p.search(text) for p in _DURABLE_PATTERNS)


class SleeptimeScheduler:
    """Background idle consolidator (in-process; not distributed)."""

    def __init__(
        self,
        consolidator: MemoryConsolidator,
        *,
        idle_seconds: float = 300.0,
        poll_seconds: float = 30.0,
        min_interval_s: float = 60.0,
        daily_hour: int | None = 3,
    ) -> None:
        self.consolidator = consolidator
        self.idle_seconds = max(5.0, idle_seconds)
        self.poll_seconds = max(1.0, poll_seconds)
        self.min_interval_s = max(0.0, min_interval_s)
        self.daily_hour = daily_hour
        self._last_activity: dict[str, float] = {}
        self._last_run: dict[str, float] = {}
        self._last_daily_key: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._stopped = asyncio.Event()

    def touch(self, session_id: str) -> None:
        sid = (session_id or "").strip() or "default"
        self._last_activity[sid] = time.time()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._loop(), name="fae-sleeptime")
        logger.info(
            "SleeptimeScheduler started idle=%ss poll=%ss",
            self.idle_seconds,
            self.poll_seconds,
        )

    async def stop(self) -> None:
        self._stopped.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("SleeptimeScheduler stopped")

    async def consolidate_now(self, session_id: str) -> ConsolidateResult:
        """Force consolidate one session (API / tests). Respects min_interval."""
        sid = (session_id or "").strip() or "default"
        async with self._lock:
            if not self._interval_ok(sid):
                return ConsolidateResult(session_id=sid, skipped="min_interval")
            result = await self.consolidator.consolidate(sid)
            if result.skipped not in {"error", "timeout", "empty"}:
                self._last_run[sid] = time.time()
            return result

    async def tick(self) -> list[ConsolidateResult]:
        """One scheduler pass — used by the loop and by unit tests."""
        now = time.time()
        results: list[ConsolidateResult] = []
        await self._maybe_daily(now, results)
        for sid, last in list(self._last_activity.items()):
            if now - last < self.idle_seconds:
                continue
            async with self._lock:
                if not self._interval_ok(sid, now=now):
                    continue
                result = await self.consolidator.consolidate(sid)
                if result.skipped not in {"error", "timeout", "empty"}:
                    self._last_run[sid] = time.time()
                results.append(result)
        return results

    def _interval_ok(self, sid: str, *, now: float | None = None) -> bool:
        if self.min_interval_s <= 0:
            return True
        last = self._last_run.get(sid)
        if last is None:
            return True
        return (now or time.time()) - last >= self.min_interval_s

    async def _maybe_daily(
        self, now: float, results: list[ConsolidateResult]
    ) -> None:
        if self.daily_hour is None:
            return
        local = time.localtime(now)
        if local.tm_hour != self.daily_hour:
            return
        day_key = time.strftime("%Y-%m-%d", local)
        if self._last_daily_key == day_key:
            return
        self._last_daily_key = day_key
        for sid in list(self._last_activity.keys()):
            async with self._lock:
                result = await self.consolidator.consolidate(sid)
                self._last_run[sid] = time.time()
                results.append(result)
        logger.info("Daily sleeptime pass day=%s sessions=%s", day_key, len(results))

    async def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                logger.exception("sleeptime tick failed")
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self.poll_seconds
                )
                return
            except TimeoutError:
                continue
