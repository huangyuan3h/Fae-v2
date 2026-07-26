"""Reflection subagent glue (Context Engineering R4).

Wires the ``MemoryConsolidator`` to a Letta-style "reflection" subagent
so the sleeptime pass can use an LLM to pick durable facts / open
questions rather than relying on regex heuristics. The reflection pass
is non-blocking: any error falls back to the deterministic path in
``MemoryConsolidator``.

The default implementation uses the FAE `run_subagent` tool with the
``reflection`` builtin prompt. A Letta-native runner can be plugged in
later by passing a different ``ReflectionRunner`` instance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Protocol

if TYPE_CHECKING:
    from fae.agent.subagents.runtime import SubagentResult
    from fae.memory.consolidation import MemoryConsolidator
    from fae.memory.recall_store import RecallTurn

logger = logging.getLogger("fae.memory.reflection")


@dataclass
class ReflectionOutcome:
    """Result of a single reflection pass — what got written to memory."""

    summary_text: str
    facts_saved: int
    current_updated: bool
    skipped: str | None = None


class ReflectionRunner(Protocol):
    """Async callable that returns None on failure (caller falls back).

    The runner receives the active consolidator + recent turns and is
    expected to mutate the memory client (set_block, save_fact) however
    it likes. Returning a ReflectionOutcome lets the caller mark
    `delegated=True` on the ConsolidateResult.
    """

    async def __call__(
        self,
        session_id: str,
        turns: list["RecallTurn"],
        consolidator: "MemoryConsolidator",
    ) -> ReflectionOutcome | None: ...


# Type alias so MemoryConsolidator.__init__ can type-annotate the field.
ReflectionRunnerFn = Callable[
    ["str", list["RecallTurn"], "MemoryConsolidator"],
    Awaitable[ReflectionOutcome | None],
]


class SubagentReflectionRunner:
    """Delegate the sleeptime consolidation to the ``reflection`` subagent.

    The reflection subagent is a builtin ``run_subagent`` task that emits
    a strict-JSON summary + facts payload. We feed the recent turns as
    the task text (capped) and apply the response to the memory client
    the same way ``RollingSummarizer`` does — write the summary block,
    upsert the facts, mirror to archival.
    """

    def __init__(
        self,
        *,
        llm,
        config,
        max_task_chars: int = 6000,
        timeout_s: float = 30.0,
        current_char_limit: int = 2000,
    ) -> None:
        self.llm = llm
        self.config = config
        self.max_task_chars = max(500, max_task_chars)
        self.timeout_s = max(1.0, timeout_s)
        self.current_char_limit = max(200, current_char_limit)

    async def __call__(
        self,
        session_id: str,
        turns: list["RecallTurn"],
        consolidator: "MemoryConsolidator",
    ) -> ReflectionOutcome | None:
        from fae.agent.subagents.runtime import run_subagent
        from fae.memory.schemas import FactIn

        task_text = _render_turns(turns, self.max_task_chars)
        try:
            result: "SubagentResult" = await run_subagent(
                "reflection",
                task=task_text,
                context="",
                llm=self.llm,
                config=self.config,
                memory=None,  # subagent sees only the task text
                session_id=session_id,
                timeout_s=self.timeout_s,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "reflection subagent failed session=%s", session_id
            )
            return None

        if not result.ok:
            logger.info(
                "reflection subagent skipped session=%s reason=%s",
                session_id, result.error,
            )
            return ReflectionOutcome(
                summary_text="", facts_saved=0, current_updated=False,
                skipped=result.error or "subagent_fail",
            )

        payload = _parse_reflection_payload(result.summary)
        if not payload:
            return ReflectionOutcome(
                summary_text="", facts_saved=0, current_updated=False,
                skipped="invalid_payload",
            )

        client = consolidator.client
        summary_text = payload["summary"][: self.current_char_limit]
        current_updated = False
        if summary_text and hasattr(client, "set_block"):
            note = _format_current_note(
                session_id, len(turns), summary_text, payload["open_questions"],
            )
            if len(note) > self.current_char_limit:
                note = note[-self.current_char_limit :]
            try:
                await client.set_block("current", note)  # type: ignore[misc]
                current_updated = True
            except Exception:  # noqa: BLE001
                logger.exception(
                    "set_block(current) failed session=%s", session_id
                )

        facts_saved = 0
        if payload["facts"] and hasattr(client, "save_fact"):
            for fact in payload["facts"]:
                txt = (fact or "").strip()
                if not txt:
                    continue
                try:
                    await client.save_fact(  # type: ignore[misc]
                        FactIn(
                            content=txt,
                            tags=["reflection", "auto"],
                            session_id=session_id,
                        )
                    )
                    facts_saved += 1
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "save_fact failed during reflection session=%s",
                        session_id,
                    )

        if consolidator.archival is not None and summary_text:
            try:
                await consolidator.archival.upsert(
                    text=summary_text,
                    session_id=session_id,
                    tags=["reflection", "recall_summary"],
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "archival upsert failed during reflection session=%s",
                    session_id,
                )

        return ReflectionOutcome(
            summary_text=summary_text,
            facts_saved=facts_saved,
            current_updated=current_updated,
        )


def _render_turns(turns: list["RecallTurn"], max_chars: int) -> str:
    """Symmetric head+tail render so newest turns survive for the LLM."""
    rendered = [
        f"[{i+1}] user: {t.user_text}\n    assistant: {t.assistant_text}"
        for i, t in enumerate(turns)
    ]
    joined = "\n".join(rendered)
    if len(joined) <= max_chars:
        return joined
    head = max_chars // 2
    tail = max_chars - head
    return f"{joined[:head]}\n... [truncated {len(joined) - max_chars} chars] ...\n{joined[-tail:]}"


def _parse_reflection_payload(content: str) -> dict | None:
    """Strict JSON parser with fence tolerance; returns None on hard fail."""
    import json

    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl > 0:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: take the first JSON-looking substring.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    summary = str(parsed.get("summary") or "").strip()
    facts = [
        str(f).strip()
        for f in (parsed.get("facts") or [])
        if str(f).strip()
    ][:10]
    questions = [
        str(q).strip()
        for q in (parsed.get("open_questions") or [])
        if str(q).strip()
    ][:5]
    if not summary and not facts and not questions:
        return None
    return {
        "summary": summary,
        "facts": facts,
        "open_questions": questions,
    }


def _format_current_note(
    session_id: str,
    n_turns: int,
    summary: str,
    open_questions: list[str],
) -> str:
    lines = [
        f"# Reflection session={session_id}",
        f"# compressed={n_turns} turns",
        "",
        "## Summary",
        summary.strip(),
    ]
    if open_questions:
        lines.append("")
        lines.append("## Open questions")
        for q in open_questions:
            q = (q or "").strip()
            if q:
                lines.append(f"- {q}")
    return "\n".join(lines).strip()