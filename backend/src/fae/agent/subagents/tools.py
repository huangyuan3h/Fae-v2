"""OpenAI-compatible run_subagent tool schema + dispatch."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fae.agent.subagents.runtime import (
    DEFAULT_TIMEOUT_S,
    SubagentResult,
    run_subagent,
)
from fae.llm.client import LLMClient
from fae.llm.types import LLMConfig
from fae.pipecat.services.letta_memory import LettaMemoryService

logger = logging.getLogger("fae.agent.subagents")

OnSubagentEvent = Callable[[dict[str, Any]], Awaitable[None]]

RUN_SUBAGENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_subagent",
        "description": (
            "Delegate a heavy subtask to a builtin specialist subagent "
            "(researcher, coder, or reviewer). Returns a citable summary. "
            "Use when the skill playbook says to research, design a patch, "
            "or review a plan. Do not nest further subagents."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": ["researcher", "coder", "reviewer"],
                    "description": "Builtin subagent to run",
                },
                "task": {
                    "type": "string",
                    "description": "Clear task for the subagent",
                },
                "context": {
                    "type": "string",
                    "description": "Optional extra context (snippets, constraints)",
                },
            },
            "required": ["name", "task"],
        },
    },
}


def format_subagent_tool_result(result: SubagentResult) -> str:
    status = "ok" if result.ok else f"failed:{result.error or 'error'}"
    return (
        f"subagent={result.name} status={status}\n"
        f"summary:\n{result.summary}"
    )


async def dispatch_run_subagent(
    arguments: str | None,
    *,
    llm: LLMClient,
    config: LLMConfig,
    memory: LettaMemoryService | None = None,
    session_id: str = "default",
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cancel_event: asyncio.Event | None = None,
    on_event: OnSubagentEvent | None = None,
) -> str:
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    name = str(args.get("name") or "").strip()
    task = str(args.get("task") or "").strip()
    context = str(args.get("context") or "").strip()

    if on_event is not None:
        try:
            await on_event(
                {
                    "type": "subagent",
                    "kind": "subagent",
                    "phase": "start",
                    "name": name or "unknown",
                    "task": task[:200],
                }
            )
        except Exception:  # noqa: BLE001
            logger.debug("subagent start event failed", exc_info=True)

    result = await run_subagent(
        name,
        task,
        context,
        llm=llm,
        config=config,
        memory=memory,
        session_id=session_id,
        timeout_s=timeout_s,
        cancel_event=cancel_event,
    )

    if on_event is not None:
        try:
            await on_event(
                {
                    "type": "subagent",
                    "kind": "subagent",
                    "phase": "done",
                    "name": result.name,
                    "ok": result.ok,
                    "error": result.error,
                    "summary": result.summary[:400],
                }
            )
        except Exception:  # noqa: BLE001
            logger.debug("subagent done event failed", exc_info=True)

    return format_subagent_tool_result(result)
