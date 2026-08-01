"""Memory injector shared by browser WS, HTTP chat, and Daily."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from fae.llm.types import ChatMessage, ChatRequest
from fae.memory.episodic import (
    detect_life_events,
    format_events_for_prompt,
)
from fae.memory.core_budget import (
    clip_recent_turns_for_budget,
    is_identity_tagged,
)
from fae.memory.fact_extract import facts_from_turn
from fae.memory.protocol import MemoryClient
from fae.memory.schemas import FactIn, FactOut

if TYPE_CHECKING:
    from fae.memory.archival import ArchivalBackend
    from fae.memory.compaction import MemoryCompactor
    from fae.memory.episodic import EpisodicStore
    from fae.memory.summarizer import RollingSummarizer

logger = logging.getLogger("fae.memory.service")

_MEMORY_TAG_OPEN = "<fae_memory>"
_MEMORY_TAG_CLOSE = "</fae_memory>"


class LettaMemoryService:
    """Fetch / persist memories around an LLM turn."""

    def __init__(
        self,
        client: MemoryClient | None = None,
        *,
        archival: ArchivalBackend | None = None,
        compactor: MemoryCompactor | None = None,
        episodic: EpisodicStore | None = None,
        summarizer: "RollingSummarizer | None" = None,
        on_persist: Callable[[str], None] | None = None,
        recent_limit: int = 10,
        events_limit: int = 8,
        facts_top_k: int = 10,
    ) -> None:
        self._client = client
        self._archival = archival
        self._compactor = compactor
        self._episodic = episodic
        self._summarizer = summarizer
        self._on_persist = on_persist
        self._recent_limit = max(0, int(recent_limit))
        self._events_limit = max(0, int(events_limit))
        self._facts_top_k = max(1, int(facts_top_k))

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> MemoryClient | None:
        return self._client

    @property
    def archival(self) -> ArchivalBackend | None:
        return self._archival

    @property
    def compactor(self) -> MemoryCompactor | None:
        return self._compactor

    @property
    def summarizer(self) -> "RollingSummarizer | None":
        return self._summarizer

    @property
    def episodic(self) -> EpisodicStore | None:
        return self._episodic

    @property
    def recent_limit(self) -> int:
        return self._recent_limit

    @property
    def events_limit(self) -> int:
        return self._events_limit

    @property
    def facts_top_k(self) -> int:
        return self._facts_top_k

    async def recall_context(
        self,
        query: str,
        *,
        session_id: str | None = None,
        top_k: int | None = None,
        char_budget: int | None = None,
    ) -> str:
        if self._client is None:
            return ""
        k = self._facts_top_k if top_k is None else max(1, int(top_k))
        try:
            base = await self._client.recall_for_prompt(
                query,
                session_id=session_id,
                top_k=k,
                recent_limit=self._recent_limit,
            )
        except Exception:  # noqa: BLE001
            logger.exception("recall_context failed")
            return ""
        if char_budget is not None and char_budget > 0:
            base = clip_recent_turns_for_budget(
                base, char_budget=char_budget,
            )
        with_archival = await self._merge_archival(
            base, query, session_id=session_id, top_k=k
        )
        return self._merge_events(with_archival, query, session_id=session_id)

    async def _merge_archival(
        self,
        base: str,
        query: str,
        *,
        session_id: str | None,
        top_k: int,
    ) -> str:
        if self._archival is None:
            return base
        if not (query or "").strip():
            return base
        try:
            scoped = await self._archival.search(
                query, top_k=top_k, session_id=session_id
            )
            # Identity / dietary memories are global — also search unscoped.
            global_hits = await self._archival.search(
                query, top_k=top_k, session_id=None
            )
        except Exception:  # noqa: BLE001
            logger.exception("archival search failed")
            return base
        by_id: dict[str, FactOut] = {}
        ordered_ids: list[str] = []
        for hit in global_hits:
            if is_identity_tagged(hit.tags):
                if hit.id not in by_id:
                    by_id[hit.id] = hit
                    ordered_ids.append(hit.id)
        for hit in scoped:
            if hit.id not in by_id:
                by_id[hit.id] = hit
                ordered_ids.append(hit.id)
        hits = [by_id[i] for i in ordered_ids]
        if not hits:
            return base
        # Prefer non-decayed hits; still include decayed at the end if needed.
        fresh = [h for h in hits if "decayed" not in (h.tags or [])]
        stale = [h for h in hits if "decayed" in (h.tags or [])]
        ordered = fresh + stale
        lines = "\n".join(f"- {h.content}" for h in ordered)
        if "[facts]" in base:
            return f"{base}\n{lines}"
        return f"{base}\n\n[facts]\n{lines}".strip()

    def _merge_events(
        self,
        base: str,
        query: str,
        *,
        session_id: str | None,
    ) -> str:
        if self._episodic is None or self._events_limit <= 0:
            return base
        try:
            events = self._episodic.list_events(
                session_id=session_id,
                limit=self._events_limit,
                query=query or None,
            )
            if not events and session_id:
                events = self._episodic.list_events(
                    session_id=session_id, limit=max(1, self._events_limit - 3),
                )
        except Exception:  # noqa: BLE001
            logger.exception("episodic list failed")
            return base
        block = format_events_for_prompt(events)
        if not block:
            return base
        return f"{base}\n\n{block}".strip() if base else block

    def inject_into_request(self, request: ChatRequest, memory_text: str) -> ChatRequest:
        """Return a copy of request with memory as a leading system message."""
        text = (memory_text or "").strip()
        if not text:
            return request
        block = (
            f"{_MEMORY_TAG_OPEN}\n"
            "Identity, durable memories, and recent conversation. "
            "[persona] is who you are and how you speak — follow it. "
            "[human] is plain-language important user facts "
            "(name, home city, preferences) — use and update via conversation; "
            "ask once when a needed fact is missing.\n"
            f"{text}\n"
            f"{_MEMORY_TAG_CLOSE}"
        )
        messages = [ChatMessage(role="system", content=block), *request.messages]
        return request.model_copy(update={"messages": messages})

    def memory_system_message(self, memory_text: str) -> dict[str, str] | None:
        """Build a system message dict for Daily LLMContext."""
        text = (memory_text or "").strip()
        if not text:
            return None
        return {
            "role": "system",
            "content": (
                f"{_MEMORY_TAG_OPEN}\n"
                "Identity, durable memories, and recent conversation. "
                "[persona] is who you are and how you speak — follow it. "
                "[human] is plain-language important user facts "
                "(name, home city, preferences) — use and update via conversation; "
                "ask once when a needed fact is missing.\n"
                f"{text}\n"
                f"{_MEMORY_TAG_CLOSE}"
            ),
        }

    async def prepare_request(
        self,
        request: ChatRequest,
        *,
        session_id: str | None = None,
        char_budget: int | None = None,
    ) -> ChatRequest:
        user_text = _last_user_text(request)
        memory = await self.recall_context(
            user_text, session_id=session_id, char_budget=char_budget,
        )
        return self.inject_into_request(request, memory)

    async def persist_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        if self._client is None:
            return
        try:
            # Previous assistant turn (before this reply) — used to detect
            # "which city?" → short answer "上海" for human-memory extraction.
            prev_assistant = ""
            try:
                recent = await self._client.list_recall(session_id, limit=1)
                if recent:
                    prev_assistant = recent[0].assistant_text or ""
            except Exception:  # noqa: BLE001
                prev_assistant = ""

            profile, facts = facts_from_turn(
                user_text=user_text,
                assistant_text=prev_assistant,
                session_id=session_id or None,
            )
            if profile is not None:
                await self._client.update_user(profile)
            saved_facts: list = []
            for fact in facts:
                saved = await self._client.save_fact(fact)
                saved_facts.append(saved)
                if self._archival is not None and is_identity_tagged(fact.tags):
                    try:
                        await self._archival.upsert(
                            text=fact.content,
                            session_id=session_id or "default",
                            tags=list(fact.tags),
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("archival upsert identity fact failed")

            await self._client.append_recall(session_id, user_text, assistant_text)
            await self._persist_episodes(session_id, user_text, saved_facts)
            # Lifecycle order: RollingSummarizer first so it can claim
            # ownership of source turns via summary_batch_id; MemoryCompactor
            # is the raw fallback and skips any turn the summarizer already
            # claimed. If the summarizer is unavailable, the compactor still
            # runs on the uncovered overflow.
            if self._summarizer is not None:
                try:
                    await self._summarizer.maybe_summarize(session_id)
                except Exception:  # noqa: BLE001
                    logger.exception("rolling summary failed session=%s", session_id)
            if self._compactor is not None:
                await self._compactor.maybe_compact(session_id)
            if self._on_persist is not None:
                self._on_persist(session_id)
        except Exception:  # noqa: BLE001
            logger.exception("persist_turn failed session=%s", session_id)

    async def _persist_episodes(
        self,
        session_id: str,
        user_text: str,
        saved_facts: list,
    ) -> None:
        if self._episodic is None:
            return
        detected = detect_life_events(user_text)
        if not detected:
            return
        for det in detected:
            event = self._episodic.add_event(
                session_id=session_id,
                kind=det.kind,
                summary=det.summary,
                raw_text=user_text,
            )
            for fact in saved_facts:
                self._episodic.link(event.id, "fact", fact.id)
            # Durable mirror into fact store for search / archival inject path.
            try:
                mirrored = await self._client.save_fact(  # type: ignore[union-attr]
                    FactIn(
                        content=det.summary,
                        tags=["episodic", det.kind],
                        session_id=session_id,
                    )
                )
                self._episodic.link(event.id, "fact", mirrored.id)
            except Exception:  # noqa: BLE001
                logger.exception("failed to mirror episodic fact")
            if self._archival is not None:
                try:
                    pid = await self._archival.upsert(
                        text=f"[event {det.kind}] {det.summary}",
                        session_id=session_id,
                    )
                    self._episodic.link(event.id, "archival", pid)
                except Exception:  # noqa: BLE001
                    logger.exception("failed to archive episodic event")


def _last_user_text(request: ChatRequest) -> str:
    for msg in reversed(request.messages):
        if msg.role == "user":
            return msg.content
    return ""
