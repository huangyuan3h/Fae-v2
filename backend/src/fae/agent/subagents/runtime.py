"""Run one builtin subagent turn; persist summary into archival."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from fae.agent.subagents.builtins import list_builtin_names, system_prompt_for
from fae.llm.client import LLMClient
from fae.llm.errors import LLMError
from fae.llm.types import ChatMessage, ChatRequest, LLMConfig
from fae.pipecat.services.letta_memory import LettaMemoryService

logger = logging.getLogger("fae.agent.subagents")

DEFAULT_TIMEOUT_S = 60.0
SUMMARY_MAX_CHARS = 1500
RECALL_MAX_CHARS = 1200


@dataclass
class SubagentResult:
    name: str
    summary: str
    ok: bool
    error: str | None = None


def _truncate(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 3] + "..."


async def run_subagent(
    name: str,
    task: str,
    context: str = "",
    *,
    llm: LLMClient,
    config: LLMConfig,
    memory: LettaMemoryService | None = None,
    session_id: str = "default",
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cancel_event: asyncio.Event | None = None,
) -> SubagentResult:
    """Delegate a short non-streaming turn to a builtin subagent."""
    key = (name or "").strip().lower()
    task_text = (task or "").strip()
    if key not in list_builtin_names():
        known = ", ".join(sorted(list_builtin_names()))
        return SubagentResult(
            name=key or name,
            summary=f"Unknown subagent {name!r}. Known: {known}",
            ok=False,
            error="unknown_name",
        )
    if not task_text:
        return SubagentResult(
            name=key,
            summary="Empty task — nothing to do.",
            ok=False,
            error="empty_task",
        )
    if cancel_event is not None and cancel_event.is_set():
        return SubagentResult(
            name=key,
            summary="Subagent cancelled before start.",
            ok=False,
            error="cancelled",
        )

    system = system_prompt_for(key) or ""
    mem_bits = ""
    if memory is not None and memory.enabled:
        try:
            mem_bits = await memory.recall_context(
                task_text, session_id=session_id, top_k=6
            )
        except Exception:  # noqa: BLE001
            logger.debug("subagent recall failed", exc_info=True)
            mem_bits = ""
    mem_bits = _truncate(mem_bits, RECALL_MAX_CHARS)
    ctx = (context or "").strip()

    user_parts = [f"Task:\n{task_text}"]
    if ctx:
        user_parts.append(f"Extra context:\n{_truncate(ctx, 800)}")
    if mem_bits:
        user_parts.append(f"Memory context:\n{mem_bits}")
    user_parts.append("Respond with a concise summary the main agent can cite.")

    req = ChatRequest(
        config=config,
        messages=[
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content="\n\n".join(user_parts)),
        ],
        temperature=0.4,
        max_tokens=900,
    )

    async def _chat() -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError()
        resp = await llm.chat(req)
        return (resp.content or "").strip()

    try:
        content = await asyncio.wait_for(_chat(), timeout=float(timeout_s))
    except TimeoutError:
        return SubagentResult(
            name=key,
            summary=f"Subagent {key} timed out after {timeout_s:.0f}s.",
            ok=False,
            error="timeout",
        )
    except asyncio.CancelledError:
        return SubagentResult(
            name=key,
            summary=f"Subagent {key} was cancelled.",
            ok=False,
            error="cancelled",
        )
    except LLMError as e:
        return SubagentResult(
            name=key,
            summary=f"Subagent {key} LLM error ({e.code}): {e.message}",
            ok=False,
            error=e.code,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("subagent %s failed", key)
        return SubagentResult(
            name=key,
            summary=f"Subagent {key} failed: {e}",
            ok=False,
            error="unknown",
        )

    if cancel_event is not None and cancel_event.is_set():
        return SubagentResult(
            name=key,
            summary=f"Subagent {key} was cancelled.",
            ok=False,
            error="cancelled",
        )

    summary = _truncate(content, SUMMARY_MAX_CHARS)
    if not summary:
        return SubagentResult(
            name=key,
            summary=f"Subagent {key} returned empty content.",
            ok=False,
            error="empty_response",
        )

    if memory is not None and memory.archival is not None:
        try:
            await memory.archival.upsert(
                text=f"[subagent:{key}] {summary}",
                session_id=session_id or "default",
                tags=["subagent", key],
            )
        except Exception:  # noqa: BLE001
            logger.exception("subagent archival upsert failed")

    return SubagentResult(name=key, summary=summary, ok=True)
