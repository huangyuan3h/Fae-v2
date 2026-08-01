"""LLM-driven rolling summary for hot recall (Context Engineering R2).

Algorithm mirrors Pipecat's ``LLMContextSummaryConfig``:
- Keep the last N turns verbatim in hot recall (Anthropic/OpenAI cache_control
  on system + tools stays intact because we never re-write the system prefix).
- Replace earlier turns with one compact summary block stored in the
  Letta ``current`` block + an archival record.

The summary LLM is configurable and defaults to the proactive / server-side
model so the main conversation bandwidth is not consumed.

Lifecycle (P1 follow-up)
------------------------

``maybe_summarize`` now claims ownership of its source turns via
``RecallStore.commit_summary_batch`` keyed by an idempotent fingerprint
``(session_id, ordered_turn_ids)``. Subsequent calls observing the same
hot window return ``SummaryResult(skipped="already_committed")`` without
re-invoking the LLM or duplicating archival / facts entries.

The committed batch row carries the canonical ``summary_text``; the
next call injects it into the prompt as a "previous rolling summary"
so successive summaries are truly cumulative instead of independent
re-summarizations. ``MemoryCompactor`` is the raw fallback — it skips
any turn whose ``summary_batch_id`` is set so a summarized turn is
never raw-archived twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fae.llm.client import LLMClient
from fae.llm.types import ChatMessage, ChatRequest, LLMConfig

if TYPE_CHECKING:
    from fae.memory.archival import ArchivalBackend
    from fae.memory.protocol import MemoryClient
    from fae.memory.recall_store import RecallStore, RecallTurn

logger = logging.getLogger("fae.memory.summarizer")


# Hard caps so the summarizer prompt can never blow the cheap model window.
_PROMPT_HEAD_CHARS = 8000
_PROMPT_TAIL_CHARS = 8000
_RECENT_KEEP_DEFAULT = 6
_TARGET_TOKENS_DEFAULT = 1200
_MAX_TOKENS_DEFAULT = 2000

# UUID namespace used for stable archival point IDs derived from a
# fingerprint. Stable namespace keeps every run of the same input set
# deterministically writing the same archival point.
_BATCH_FINGERPRINT_NS = uuid.UUID("6f1d9c19-4d7a-4f63-8f4b-7b9a6c5d3e21")


_SUMMARY_SYSTEM_PROMPT = (
    "You compress a chat transcript into a single rolling summary block. "
    "You may also be given a previous rolling summary — merge any durable "
    "facts from it into the new summary instead of dropping them. "
    "Keep: durable facts about the user (name, location, preferences, ongoing "
    "projects), unresolved questions, and explicit commitments. Drop: greetings, "
    "filler, and any sentence that adds no information. "
    "Output strict JSON of the form "
    '{"summary": "<= 600 chars prose, in the user primary language>", '
    '"open_questions": ["..."], "facts": ["..."]}. '
    "Do not include any prose outside the JSON."
)


@dataclass
class SummaryResult:
    session_id: str
    summarized_turns: int
    kept_recent: int
    summary_text: str
    facts: list[str]
    open_questions: list[str]
    target_block: str = "current"
    elapsed_s: float = 0.0
    skipped: str | None = None
    batch_id: str | None = None
    archive_point_id: str | None = None


class RollingSummarizer:
    """LLM-driven rolling summary over hot recall turns.

    Trigger conditions (all configurable):
    - hot turn count >= ``max_turns`` (default 30) — the same threshold as
      ``MemoryCompactor`` so this layer is one rung above it
    - estimated char count >= ``max_chars`` (default 9000)

    Behaviour:
    - Selects oldest *uncovered* turns (those without an existing
      ``summary_batch_id``) and skips the most recent ``recent_keep``
      turns so they remain verbatim.
    - Computes a fingerprint from ``(session_id, ordered_turn_ids)``. If
      a batch row already exists for the fingerprint the call returns
      ``SummaryResult(skipped="already_committed")`` without invoking
      the LLM, ensuring idempotency across retries.
    - Injects the previous batch's summary_text into the prompt so the
      new summary is cumulative rather than re-derived from scratch.
    - On LLM success: writes the canonical block + archival (with a
      deterministic ``point_id`` derived from the fingerprint) + facts,
      then commits a batch row that atomically claims the source
      turns' ``summary_batch_id``. The compactor will skip these turns.
    - On LLM failure: returns ``skipped="timeout"`` / ``"error"`` without
      committing, leaving the turns for the raw compactor fallback.

    This is non-destructive: original ``RecallTurn`` rows are kept so a
    later sleeptime / context-archaeology pass can still surface them.
    """

    def __init__(
        self,
        llm: LLMClient,
        config: LLMConfig,
        *,
        recall: "RecallStore",
        client: "MemoryClient",
        archival: "ArchivalBackend | None" = None,
        max_turns: int = 30,
        max_chars: int = 9000,
        recent_keep: int = _RECENT_KEEP_DEFAULT,
        target_block: str = "current",
        current_char_limit: int = 2000,
        target_tokens: int = _TARGET_TOKENS_DEFAULT,
        max_tokens: int = _MAX_TOKENS_DEFAULT,
        timeout_s: float = 30.0,
    ) -> None:
        self.llm = llm
        self.config = config
        self.recall = recall
        self.client = client
        self.archival = archival
        self.max_turns = max(2, max_turns)
        self.max_chars = max(500, max_chars)
        self.recent_keep = max(1, recent_keep)
        self.target_block = target_block
        self.current_char_limit = max(200, current_char_limit)
        self.target_tokens = max(64, target_tokens)
        self.max_tokens = max(self.target_tokens, max_tokens)
        self.timeout_s = max(1.0, timeout_s)

    async def maybe_summarize(self, session_id: str) -> SummaryResult | None:
        sid = (session_id or "").strip() or "default"
        hot = self.recall.list_hot(sid, limit=10_000)
        if len(hot) < self.max_turns:
            return None
        char_total = sum(
            len(t.user_text) + len(t.assistant_text) for t in hot
        )
        if char_total < self.max_chars and len(hot) < self.max_turns * 2:
            return None

        # Pick only turns the summarizer hasn't already claimed.
        candidate_n = max(1, len(hot) - self.recent_keep)
        # Compute the fingerprint over the *logical* window (oldest
        # ``len(hot) - recent_keep`` turns) so a subsequent call observing
        # the same hot window hits the idempotent short-circuit even when
        # ``peek_oldest_uncovered`` returns 0 rows because the previous
        # commit already covered them.
        fingerprint = self._fingerprint_for(sid, hot[:candidate_n])
        existing = self.recall.find_batch_by_fingerprint(sid, fingerprint)
        if existing is not None:
            kept_count = max(0, len(hot) - candidate_n)
            kept = hot[-kept_count:] if kept_count else []
            return SummaryResult(
                session_id=sid,
                summarized_turns=candidate_n,
                kept_recent=len(kept),
                summary_text=existing.get("summary_text", "") or "",
                facts=[],
                open_questions=[],
                target_block=self.target_block,
                skipped="already_committed",
                batch_id=existing.get("batch_id"),
                archive_point_id=existing.get("batch_id"),
            )

        to_summarize = self.recall.peek_oldest_uncovered(sid, candidate_n)
        if not to_summarize:
            # Window grew but everything uncovered has been claimed by an
            # earlier batch whose fingerprint differs (e.g. a turn was
            # appended between batches). Nothing to do.
            return None
        # ``kept`` is the most-recent turns in the hot window — at least
        # ``recent_keep`` rows survive verbatim. Anything between
        # ``to_summarize[-1]`` and ``kept[0]`` would be covered-only
        # turns (already summarized previously) and is dropped from
        # the candidate set.
        kept_count = max(0, len(hot) - len(to_summarize))
        kept = hot[-kept_count:] if kept_count else []

        previous = self.recall.latest_batch(sid)
        previous_summary = (previous or {}).get("summary_text") or ""

        started = time.monotonic()
        try:
            async with asyncio.timeout(self.timeout_s):
                payload = await self._call_summary_llm(
                    to_summarize, previous_summary=previous_summary
                )
        except TimeoutError:
            logger.warning("rolling summary timeout sid=%s", sid)
            return SummaryResult(
                session_id=sid,
                summarized_turns=len(to_summarize),
                kept_recent=len(kept),
                summary_text="",
                facts=[],
                open_questions=[],
                target_block=self.target_block,
                elapsed_s=time.monotonic() - started,
                skipped="timeout",
            )
        except Exception:  # noqa: BLE001
            logger.exception("rolling summary LLM call failed sid=%s", sid)
            return SummaryResult(
                session_id=sid,
                summarized_turns=len(to_summarize),
                kept_recent=len(kept),
                summary_text="",
                facts=[],
                open_questions=[],
                target_block=self.target_block,
                elapsed_s=time.monotonic() - started,
                skipped="error",
            )

        summary_text = payload["summary"][: self.current_char_limit]
        facts = payload.get("facts") or []
        open_questions = payload.get("open_questions") or []
        batch_id = str(uuid.uuid5(_BATCH_FINGERPRINT_NS, fingerprint))
        point_id = batch_id  # Stable archival point ID across retries.

        # Inject into the persistent block (overwrite, not append).
        if hasattr(self.client, "set_block"):
            note = self._format_current_note(
                sid=sid,
                summarized=len(to_summarize),
                kept=len(kept),
                summary=summary_text,
                open_questions=open_questions,
                batch_id=batch_id,
            )
            try:
                await self.client.set_block(self.target_block, note)  # type: ignore[misc]
            except Exception:  # noqa: BLE001
                logger.exception(
                    "set_block(%s) failed sid=%s", self.target_block, sid
                )

        # Mirror into archival so future recall can surface it.
        if self.archival is not None and summary_text:
            try:
                await self.archival.upsert(
                    text=summary_text,
                    session_id=sid,
                    point_id=point_id,
                    tags=["recall_summary", "rolling"],
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "archival upsert failed sid=%s", sid
                )

        # Promote any extracted facts through the normal fact pipeline.
        if facts and hasattr(self.client, "save_fact"):
            from fae.memory.schemas import FactIn

            for fact_text in facts:
                txt = (fact_text or "").strip()
                if not txt:
                    continue
                try:
                    await self.client.save_fact(  # type: ignore[misc]
                        FactIn(
                            content=txt,
                            tags=["rolling_summary", "auto"],
                            session_id=sid,
                        )
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("save_fact failed during summarize sid=%s", sid)

        committed = self.recall.commit_summary_batch(
            session_id=sid,
            fingerprint=fingerprint,
            turn_ids=[t.id for t in to_summarize],
            summary_text=summary_text,
            batch_id=batch_id,
        )
        if committed is None:
            # Another worker raced us to the same fingerprint — treat as
            # idempotent success but report the canonical batch id.
            existing = self.recall.find_batch_by_fingerprint(sid, fingerprint)
            if existing is not None:
                return SummaryResult(
                    session_id=sid,
                    summarized_turns=len(to_summarize),
                    kept_recent=len(kept),
                    summary_text=existing.get("summary_text", "") or summary_text,
                    facts=[],
                    open_questions=[],
                    target_block=self.target_block,
                    elapsed_s=time.monotonic() - started,
                    skipped="already_committed",
                    batch_id=existing.get("batch_id"),
                    archive_point_id=existing.get("batch_id"),
                )

        return SummaryResult(
            session_id=sid,
            summarized_turns=len(to_summarize),
            kept_recent=len(kept),
            summary_text=summary_text,
            facts=facts,
            open_questions=open_questions,
            target_block=self.target_block,
            elapsed_s=time.monotonic() - started,
            batch_id=batch_id,
            archive_point_id=point_id,
        )

    # ── private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _fingerprint_for(session_id: str, turns: list["RecallTurn"]) -> str:
        """Stable fingerprint over (session_id, ordered turn IDs).

        Two ``maybe_summarize`` calls observing the same source turn
        window produce the same fingerprint so the second hits the
        ``already_committed`` short-circuit.
        """
        ordered = "|".join(t.id for t in turns)
        h = hashlib.sha256(f"{session_id}::{ordered}".encode("utf-8")).hexdigest()
        return h[:32]

    async def _call_summary_llm(
        self,
        turns: list["RecallTurn"],
        *,
        previous_summary: str = "",
    ) -> dict[str, Any]:
        transcript = self._render_transcript(turns)
        prev_block = ""
        if previous_summary.strip():
            prev_block = (
                "<previous_summary>\n"
                f"{previous_summary.strip()}\n"
                "</previous_summary>\n\n"
                "Merge durable facts from <previous_summary> into the new "
                "summary instead of dropping them.\n\n"
            )
        user_msg = (
            "Compress the following conversation transcript into a rolling "
            "summary. Strict JSON only.\n\n"
            f"{prev_block}"
            f"<transcript>\n{transcript}\n</transcript>"
        )
        req = ChatRequest(
            config=self.config,
            messages=[
                ChatMessage(role="system", content=_SUMMARY_SYSTEM_PROMPT),
                ChatMessage(role="user", content=user_msg),
            ],
            temperature=0.2,
            max_tokens=self.max_tokens,
        )
        resp = await self.llm.chat(req)
        return _parse_summary_payload(resp.content or "")

    def _render_transcript(self, turns: list["RecallTurn"]) -> str:
        head: list[str] = []
        tail: list[str] = []
        budget = _PROMPT_HEAD_CHARS + _PROMPT_TAIL_CHARS
        rendered = [
            f"[{i+1}] user: {t.user_text}\n    assistant: {t.assistant_text}"
            for i, t in enumerate(turns)
        ]
        joined = "\n".join(rendered)
        if len(joined) <= budget:
            return joined
        # Symmetric head + tail truncation so newest turns survive verbatim.
        head_budget = _PROMPT_HEAD_CHARS
        tail_budget = _PROMPT_TAIL_CHARS
        head_str = joined[:head_budget]
        tail_str = joined[-tail_budget:]
        return f"{head_str}\n... [truncated {len(joined) - head_budget - tail_budget} chars] ...\n{tail_str}"

    def _format_current_note(
        self,
        *,
        sid: str,
        summarized: int,
        kept: int,
        summary: str,
        open_questions: list[str],
        batch_id: str | None = None,
    ) -> str:
        lines = [
            f"# Rolling summary session={sid}",
            f"# compressed={summarized} turns, kept last {kept} verbatim",
        ]
        if batch_id:
            lines.append(f"# batch_id={batch_id}")
        lines.append("")
        lines.append("## Summary")
        lines.append(summary.strip())
        if open_questions:
            lines.append("")
            lines.append("## Open questions")
            for q in open_questions:
                q = (q or "").strip()
                if q:
                    lines.append(f"- {q}")
        text = "\n".join(lines).strip()
        if len(text) > self.current_char_limit:
            text = text[-self.current_char_limit :]
        return text


def _parse_summary_payload(content: str) -> dict[str, Any]:
    """Parse strict-JSON summary content; tolerate fences / minor noise."""
    text = (content or "").strip()
    if not text:
        return {"summary": "", "facts": [], "open_questions": []}
    if text.startswith("```"):
        # Strip leading ```json fence if the model added one.
        first_nl = text.find("\n")
        if first_nl > 0:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "summary LLM returned non-JSON (%d chars); falling back to prose",
            len(text),
        )
        return {
            "summary": text[:600],
            "facts": [],
            "open_questions": [],
        }
    summary = str(parsed.get("summary") or "").strip()
    facts_raw = parsed.get("facts") or []
    questions_raw = parsed.get("open_questions") or []
    facts = [str(f).strip() for f in facts_raw if str(f).strip()]
    questions = [str(q).strip() for q in questions_raw if str(q).strip()]
    return {
        "summary": summary,
        "facts": facts,
        "open_questions": questions,
    }


def build_default_summarizer(
    settings,
    stack,
    llm_client: LLMClient,
) -> "RollingSummarizer | None":
    """Construct a RollingSummarizer from app settings + memory stack.

    Returns None when the server-side LLM is not configured (so the caller
    can opt out gracefully).
    """
    from fae.channels.bridge import resolve_server_llm_config

    cfg = resolve_server_llm_config(settings)
    if cfg is None or stack.client is None or stack.recall is None:
        return None
    return RollingSummarizer(
        llm=llm_client,
        config=cfg,
        recall=stack.recall,
        client=stack.client,
        archival=stack.archival,
        max_turns=settings.recall_max_turns,
        current_char_limit=settings.core_current_char_limit,
    )