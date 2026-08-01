"""Plan Mode tool — a unified ``update_plan`` OpenAI tool the agent can
call to create a plan, claim a step, complete / block / cancel a step,
or unblock a previously-blocked step.

Server-side dispatcher writes through ``PlanStore`` and emits WS events
(``plan_created`` / ``plan_step_update`` / ``plan_completed``) so the FE
stays in sync.

The tool is always available — it is cheap and acts as the agent's
self-described execution log. Auto-detect (pre-turn check) decides when
the agent is encouraged to call ``update_plan(action=create)``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping

from fae.plans import Plan, PlanStore, PlanStep, PlanStepStatus

if TYPE_CHECKING:
    from fae.llm.client import LLMClient
    from fae.llm.types import ChatRequest, ChatMessage, LLMConfig

logger = logging.getLogger("fae.agent.plan_tools")


UPDATE_PLAN_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_plan",
        "description": (
            "Track a multi-step plan for the current task. Call once with "
            "action=create to publish the plan up front; then call claim / "
            "complete / block / unblock / cancel to update step status. Use "
            "this to make progress visible to the user across turns. "
            "Reengage rule: if any step is currently blocked (look for the "
            "<active_plan> marker [!] blocked) and the user has just sent a "
            "new message that answers the block, you MUST call "
            "update_plan(action=unblock, step_index=N, note=<user answer>) "
            "BEFORE claim/complete on that step so the user-provided info is "
            "recorded. If the user wants to abort the step instead, call "
            "action=cancel with step_index=N."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create",
                        "claim",
                        "complete",
                        "block",
                        "unblock",
                        "cancel",
                    ],
                    "description": "What to do.",
                },
                "title": {
                    "type": "string",
                    "description": "Plan title (create only).",
                },
                "summary": {
                    "type": "string",
                    "description": "Optional plan summary (create only).",
                },
                "steps": {
                    "type": "array",
                    "description": "Step list (create only).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "acceptance": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                },
                "step_index": {
                    "type": "integer",
                    "description": "0-based step index for claim/complete/block/unblock/cancel.",
                },
                "note": {
                    "type": "string",
                    "description": (
                        "Optional note. For unblock, pass the user's answer so "
                        "the note records it; for block, the missing-info reason; "
                        "for complete/cancel, an outcome summary."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}


@dataclass
class PlanToolEvent:
    """Server-side event surfaced via the WS layer for FE sync."""

    type: str
    plan_id: str
    plan: Plan | None = None
    step: PlanStep | None = None


PlanEventEmitter = Callable[[PlanToolEvent], Awaitable[None] | None]


def _serialise_plan(plan: Plan, store: PlanStore) -> dict[str, Any]:
    return store.to_dict(plan)


async def _emit(emitter: PlanEventEmitter | None, event: PlanToolEvent) -> None:
    if emitter is None:
        return
    try:
        result = emitter(event)
        if hasattr(result, "__await__"):
            await result
    except Exception:
        logger.exception("plan event emit failed (type=%s)", event.type)


def dispatch_update_plan(
    arguments: Mapping[str, Any] | str,
    *,
    session_id: str,
    plan_store: PlanStore,
    on_event: PlanEventEmitter | None = None,
) -> str:
    """Apply an ``update_plan`` tool call against the store.

    Returns a short text summary for the LLM (so it can confirm the
    update and continue). Emits ``plan_created`` / ``plan_step_update`` /
    ``plan_completed`` to the WS layer for FE sync.

    Raises:
        ValueError: missing fields / unknown step / invalid transition.
    """
    args: dict[str, Any] = dict(arguments) if not isinstance(arguments, str) else _safe_load_json(arguments)
    action = str(args.get("action") or "").strip()
    if not action:
        raise ValueError("update_plan: missing 'action'")

    if action == "create":
        return _dispatch_create(args, session_id, plan_store, on_event)
    if action in ("claim", "complete", "block", "unblock", "cancel"):
        return _dispatch_step_update(action, args, session_id, plan_store, on_event)
    raise ValueError(f"update_plan: unknown action {action!r}")


def _dispatch_create(
    args: dict[str, Any],
    session_id: str,
    plan_store: PlanStore,
    on_event: PlanEventEmitter | None,
) -> str:
    title = str(args.get("title") or "").strip()
    if not title:
        raise ValueError("update_plan(create): 'title' is required")
    summary = str(args.get("summary") or "").strip()
    raw_steps = args.get("steps") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("update_plan(create): 'steps' must be a non-empty list")
    parsed_steps: list[dict[str, str]] = []
    for s in raw_steps:
        if not isinstance(s, dict):
            raise ValueError("update_plan(create): each step must be an object")
        parsed_steps.append(
            {
                "title": str(s.get("title") or "").strip(),
                "acceptance": str(s.get("acceptance") or "").strip(),
            }
        )
    parsed_steps = [s for s in parsed_steps if s["title"]]
    if not parsed_steps:
        raise ValueError("update_plan(create): no steps had a title")
    plan = plan_store.create_plan(session_id, title, summary, parsed_steps)
    _emit_sync(on_event, PlanToolEvent(type="plan_created", plan_id=plan.id, plan=plan))
    return (
        f"plan created ({len(plan.steps)} steps). "
        f"Continue working through each step and call update_plan(action=claim|complete|...) to keep state in sync."
    )


def _dispatch_step_update(
    action: str,
    args: dict[str, Any],
    session_id: str,
    plan_store: PlanStore,
    on_event: PlanEventEmitter | None,
) -> str:
    step_index = args.get("step_index")
    if not isinstance(step_index, int) or step_index < 0:
        raise ValueError(f"update_plan({action}): 'step_index' must be a non-negative int")
    note = args.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError(f"update_plan({action}): 'note' must be a string")

    active = plan_store.get_active_for_session(session_id)
    if active is None:
        raise ValueError(f"update_plan({action}): no active plan for session")
    if step_index >= len(active.steps):
        raise ValueError(
            f"update_plan({action}): step_index {step_index} out of range "
            f"(plan has {len(active.steps)} steps)"
        )
    step_id = active.steps[step_index].id

    if action == "claim":
        step = plan_store.claim_step(step_id)
        event_type = "plan_step_update"
    elif action == "complete":
        step = plan_store.complete_step(step_id, note=note)
        event_type = "plan_step_completed" if _plan_now_completed(plan_store, step.plan_id) else "plan_step_update"
    elif action == "block":
        step = plan_store.block_step(step_id, reason=note or "")
        event_type = "plan_step_update"
    elif action == "unblock":
        step = plan_store.unblock_step(step_id, note=note)
        event_type = "plan_step_update"
    elif action == "cancel":
        step = plan_store.cancel_step(step_id, note=note)
        event_type = "plan_step_completed" if _plan_now_completed(plan_store, step.plan_id) else "plan_step_update"
    else:  # pragma: no cover — guarded above
        raise ValueError(f"update_plan: unknown step action {action!r}")

    _emit_sync(
        on_event,
        PlanToolEvent(
            type=event_type,
            plan_id=step.plan_id,
            plan=plan_store.get_plan(step.plan_id),
            step=step,
        ),
    )
    return f"plan step {step_index} ({step.title}) -> {step.status}"


def _plan_now_completed(plan_store: PlanStore, plan_id: str) -> bool:
    plan = plan_store.get_plan(plan_id)
    if plan is None:
        return False
    return plan.status == "completed"


def _emit_sync(
    emitter: PlanEventEmitter | None,
    event: PlanToolEvent,
) -> None:
    """Run the (possibly async) emitter from a sync context."""
    if emitter is None:
        return
    try:
        result = emitter(event)
        if hasattr(result, "__await__"):
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(result)
            else:
                loop.create_task(result)
    except Exception:
        logger.exception("plan event emit failed (type=%s)", event.type)


def _safe_load_json(raw: str) -> dict[str, Any]:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"update_plan: invalid JSON arguments: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("update_plan: arguments must decode to an object")
    return loaded


def active_plan_as_prompt_block(plan: Plan) -> str:
    """Format the active plan as a system-prompt block so the agent can
    pick up where it left off across turns."""
    if not plan.is_active:
        return ""
    lines = [
        "<active_plan>",
        f"title: {plan.title}",
    ]
    if plan.summary:
        lines.append(f"summary: {plan.summary}")
    lines.append("steps:")
    for step in plan.steps:
        marker = _STATUS_GLYPH.get(step.status, "?")
        acc = f" (acceptance: {step.acceptance})" if step.acceptance else ""
        note = f" — {step.note}" if step.note else ""
        lines.append(f"  {step.index}. [{marker}] {step.status}: {step.title}{acc}{note}")
    lines.append("</active_plan>")
    lines.append(
        "Use the update_plan tool to keep this plan's status accurate. "
        "Mark the current step in_progress, then complete or block it before moving on."
    )
    return "\n".join(lines)


def find_blocked_steps(plan: Plan) -> list[PlanStep]:
    """Return steps that are currently blocked (for user re-engagement)."""
    if not plan.is_active:
        return []
    return [s for s in plan.steps if s.status == PlanStepStatus.BLOCKED.value]


def user_response_for_blocked_block(plan: Plan) -> str:
    """System-prompt block that names any blocked step(s) on the active
    plan. Combined with the user message, it nudges the LLM to call
    ``update_plan(action=unblock, step_index=N, note=<user answer>)`` on
    its next tool turn rather than skipping past the block.
    """
    blocked = find_blocked_steps(plan)
    if not blocked:
        return ""
    lines = ["<user_response_for_blocked>"]
    lines.append(
        "The active plan has the following blocked step(s). Treat the user's "
        "current message as their response to the first blocked step unless "
        "they explicitly say otherwise; call update_plan(action=unblock, "
        "step_index=N, note=<the user's answer>) before claiming/completing "
        "that step, or update_plan(action=cancel, step_index=N) if they want "
        "to drop it."
    )
    for step in blocked:
        lines.append(f"- step_index={step.index}: {step.title}")
        if step.note:
            lines.append(f"  last_block_reason: {step.note}")
    lines.append("</user_response_for_blocked>")
    return "\n".join(lines)


_STATUS_GLYPH: dict[str, str] = {
    PlanStepStatus.PENDING.value: " ",
    PlanStepStatus.IN_PROGRESS.value: "▶",
    PlanStepStatus.COMPLETED.value: "✓",
    PlanStepStatus.BLOCKED.value: "!",
    PlanStepStatus.CANCELLED.value: "x",
}


_PLAN_MODE_INSTRUCTION = (
    "This looks like a multi-step task. Before you start working, "
    "call update_plan(action=create, title=..., summary=..., steps=[...]) to "
    "publish a plan to the user. Then for each step call "
    "update_plan(action=claim, step_index=N) when you start, and "
    "update_plan(action=complete|block|cancel, step_index=N) when you finish. "
    "Use the plan to keep the user oriented across turns. "
    "Reengage rule: when the <active_plan> block contains a blocked step and "
    "the user just sent new input on this turn, you MUST first call "
    "update_plan(action=unblock, step_index=N, note=<the user's answer>) so "
    "the resolution is recorded before you claim/complete that step. If the "
    "user instead wants to drop the step, call action=cancel with step_index=N."
)

_PLAN_DETECT_PROMPT = (
    "Decide whether the user's request below requires a multi-step plan "
    "with 2 or more dependent steps (e.g. migration, research+write, "
    "investigate+patch+verify, set up a workflow). Reply with exactly one "
    "word: YES or NO. Single quick answers do NOT need a plan.\n\n"
    "Request:\n{user_text}"
)


async def should_auto_plan(
    client: "LLMClient",
    config: "LLMConfig",
    user_text: str,
    *,
    max_tokens: int = 4,
) -> bool:
    """Return True if the LLM judges the user request needs a plan.

    Cheap pre-flight check — one short completion. Caller should already
    have verified there is no active plan for the session before invoking.
    """
    from fae.llm.types import ChatRequest, ChatMessage

    prompt = _PLAN_DETECT_PROMPT.format(user_text=user_text[:1500])
    req = ChatRequest(
        config=config,
        messages=[
            ChatMessage(role="system", content="You are a triage classifier. Reply with one word: YES or NO."),
            ChatMessage(role="user", content=prompt),
        ],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    try:
        response = await client.chat(req)
    except Exception:
        logger.exception("plan auto-detect LLM call failed; defaulting to no plan")
        return False
    answer = (response.content or "").strip().upper()
    if answer.startswith("Y"):
        return True
    if answer.startswith("N"):
        return False
    return False


def inject_plan_directive(
    request: "ChatRequest",
) -> "ChatRequest":
    """Append a one-shot Plan Mode directive to the system message so the
    model is encouraged to publish a plan on the next assistant turn.
    Idempotent — calling twice does not stack the directive.
    """
    from fae.llm.types import ChatMessage

    if not request.messages:
        return request.model_copy(
            update={"messages": [ChatMessage(role="system", content=_PLAN_MODE_INSTRUCTION)]}
        )
    new_messages: list = []
    has_system = False
    for msg in request.messages:
        if msg.role == "system":
            has_system = True
            if _PLAN_MODE_INSTRUCTION not in msg.content:
                new_messages.append(
                    ChatMessage(
                        role="system",
                        content=msg.content.rstrip() + "\n\n" + _PLAN_MODE_INSTRUCTION,
                    )
                )
            else:
                new_messages.append(msg)
        else:
            new_messages.append(msg)
    if not has_system:
        new_messages.insert(0, ChatMessage(role="system", content=_PLAN_MODE_INSTRUCTION))
    return request.model_copy(update={"messages": new_messages})