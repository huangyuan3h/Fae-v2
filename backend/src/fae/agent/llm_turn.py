"""Run one assistant turn with optional LAZY request_skill + tools."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fae.agent.skills_runtime import SkillActivationInfo, SkillRuntime
from fae.agent.subagents.tools import dispatch_run_subagent
from fae.agent.tool_offload import ToolOffloader, maybe_offload_result
from fae.approvals import (
    ApprovalStore,
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_EXPIRED,
    STATUS_CANCELLED,
    STATUS_AWAITING_CONFIRM,
    request_approval,
)
from fae.llm.client import LLMClient
from fae.llm.types import ChatMessage, ChatRequest, ChatResponse
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.scheduler.tools import dispatch_schedule_tool
from fae.tool_registry import (
    EffectivePolicy,
    PolicyDecision,
    diff_preview_for,
    group_for,
    is_coding_tool,
    iter_openai_schemas,
    resolve_policy,
    resolve_timeout,
    specs_in_group,
)
from fae.tools.bash import dispatch_bash_tool
from fae.tools.filesystem import dispatch_filesystem_tool
from fae.tools.git import dispatch_git_tool
from fae.tools.weather import dispatch_weather_tool

if TYPE_CHECKING:
    from fae.scheduler.store import ScheduleStore

logger = logging.getLogger("fae.agent.skills")

_MAX_TOOL_ROUNDS = 6

# Tool-name allow-lists derived from the unified registry. The registry owns
# the canonical list per group; we freeze them at import time so dispatchers
# can do O(1) membership tests without locking.
_SCHEDULE_TOOL_NAMES: frozenset[str] = frozenset(
    s.name for s in specs_in_group("schedule")
)
_WEATHER_TOOL_NAMES: frozenset[str] = frozenset(
    s.name for s in specs_in_group("weather")
)
_FILESYSTEM_TOOL_NAMES: frozenset[str] = frozenset(
    s.name for s in specs_in_group("filesystem")
)
_BASH_TOOL_NAMES: frozenset[str] = frozenset(
    s.name for s in specs_in_group("bash")
)
_GIT_TOOL_NAMES: frozenset[str] = frozenset(
    s.name for s in specs_in_group("git")
)

OnSubagentEvent = Callable[[dict[str, Any]], Awaitable[None]]
OnToolEvent = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit_tool_event(
    callback: OnToolEvent | None,
    event: dict[str, Any],
) -> None:
    if callback is None:
        return
    tagged = dict(event)
    if not tagged.get("kind") and tagged.get("type") == "tool":
        tagged["kind"] = "tool"
    try:
        await callback(tagged)
    except Exception:
        logger.exception("Tool event handler failed")


def _tool_result_ok(result: str) -> bool:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return True
    return bool(payload.get("ok", True)) if isinstance(payload, dict) else True



def _strip_tools(request: ChatRequest) -> ChatRequest:
    if request.tools is None and request.tool_choice is None:
        return request
    return request.model_copy(update={"tools": None, "tool_choice": None})


def _append_unique_tools(tools: list[dict], extra: list[dict]) -> None:
    names = {
        t.get("function", {}).get("name")
        for t in tools
        if isinstance(t, dict)
    }
    for t in extra:
        n = t.get("function", {}).get("name")
        if n not in names:
            tools.append(t)
            names.add(n)


def activation_wants_subagent(
    activation: SkillActivationInfo,
    skills: SkillRuntime | None,
) -> bool:
    """True when an active skill declares requires_tools: [run_subagent]."""
    if skills is None or not activation.active:
        return False
    by_name = {s.meta.name: s for s in skills._skills_with_meta()}
    for name in activation.active:
        skill = by_name.get(name)
        if skill is None:
            continue
        required = skill.meta.requires_tools or []
        if "run_subagent" in required:
            return True
    return False


def _merge_tools(
    activation: SkillActivationInfo,
    schedule_store: ScheduleStore | None,
    *,
    weather_enabled: bool = False,
    attach_subagent: bool = False,
    filesystem_enabled: bool = False,
    bash_enabled: bool = False,
    git_enabled: bool = False,
) -> list[dict]:
    """Compose the LLM-facing tool list from skill + feature flags.

    Tools are sourced from the unified registry (``fae.tool_registry``); the
    registry owns the OpenAI schemas and policy metadata, while feature
    flags map to registry groups.
    """
    tools = list(activation.tools or [])
    if schedule_store is not None:
        _append_unique_tools(tools, list(iter_openai_schemas("schedule")))
    if weather_enabled:
        _append_unique_tools(tools, list(iter_openai_schemas("weather")))
    if attach_subagent:
        _append_unique_tools(tools, list(iter_openai_schemas("subagent")))
    if filesystem_enabled:
        _append_unique_tools(tools, list(iter_openai_schemas("filesystem")))
    if bash_enabled:
        _append_unique_tools(tools, list(iter_openai_schemas("bash")))
    if git_enabled:
        _append_unique_tools(tools, list(iter_openai_schemas("git")))
    return tools


def _tool_result_message(tool_name: str, result: str) -> ChatMessage:
    return ChatMessage(
        role="system",
        content=(
            f'<tool_result name="{tool_name}">\n{result}\n</tool_result>\n'
            "Use this tool result to continue the task. If more tool actions are "
            "needed, call the next tool. Never claim an action succeeded when the "
            "result reports an error."
        ),
    )


def _offloaded_tool_result_message(
    tool_name: str,
    body: str,
    offload_path: str,
    full_chars: int,
) -> ChatMessage:
    """Wrap an offloaded tool result so the agent knows where to find it.

    The replacement body is byte-stable for a given offload path so the
    surrounding prefix cache survives across turns.
    """
    envelope = (
        f'<tool_result name="{tool_name}" offloaded="true" '
        f'path="{offload_path}" full_chars="{full_chars}">\n{body}\n</tool_result>\n'
        "The full result body was offloaded to disk to keep context small. "
        "Use the read_file tool on the path above to pull it back when you "
        "need details beyond the preview. Do not re-invoke the original tool."
    )
    return ChatMessage(role="system", content=envelope)


async def _wrap_tool_result(
    offloader: ToolOffloader | None,
    tool_name: str,
    call_id: str,
    result: str,
) -> ChatMessage:
    """Build the prompt-side tool_result message; offload when oversized."""
    body, off = await maybe_offload_result(
        offloader,
        tool_name=tool_name,
        call_id=call_id,
        result=result,
    )
    if off is not None and not off.skipped and off.path:
        return _offloaded_tool_result_message(
            tool_name, body, off.path, off.chars_written,
        )
    return _tool_result_message(tool_name, result)


async def _dispatch_coding_tool(
    tool_name: str,
    arguments: str,
    *,
    call_id: str = "",
    workspace_root: str = "",
    tool_offload_dir: str = "",
    filesystem_enabled: bool = False,
    bash_enabled: bool = False,
    bash_timeout_s: float = 30.0,
    git_enabled: bool = False,
    git_timeout_s: float = 20.0,
    session_id: str = "default",
    channel: str = "unknown",
    channel_id: str | None = None,
    on_tool_event: OnToolEvent | None = None,
    approval_store: ApprovalStore | None = None,
    effective_policy: EffectivePolicy | None = None,
    trace_turn_id: str | None = None,
    cancel_event: asyncio.Event | None = None,
) -> str | None:
    enabled = (
        (filesystem_enabled and tool_name in _FILESYSTEM_TOOL_NAMES)
        or (bash_enabled and tool_name in _BASH_TOOL_NAMES)
        or (git_enabled and tool_name in _GIT_TOOL_NAMES)
    )
    if not enabled:
        return None
    event_id = call_id or f"{tool_name}-{id(arguments)}"

    # ── Approval gate (sensitive / dangerous tools) ─────────────────────
    approval_status = "not_required"
    approval_id: str | None = None
    decision = resolve_policy(
        effective_policy, tool_name, channel=channel
    )
    if not decision.allow and approval_store is not None:
        requester = (
            f"agent:{trace_turn_id or 'unknown'}" if trace_turn_id else "agent"
        )

        async def _approval_emit(ev: dict[str, Any]) -> None:
            if on_tool_event is None:
                return
            await on_tool_event(
                {
                    "type": "approval_request",
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                    **ev,
                }
            )

        resolved = await request_approval(
            approval_store,
            tool_name=tool_name,
            arguments=arguments,
            session_id=session_id,
            turn_id=trace_turn_id,
            channel=channel,
            channel_id=channel_id,
            requester=requester,
            on_event=_approval_emit,
            cancel_event=cancel_event,
        )
        approval_id = resolved.id
        approval_status = resolved.status
        if resolved.status in {STATUS_DENIED, STATUS_EXPIRED, STATUS_CANCELLED}:
            reason_code = (
                "approval_denied"
                if resolved.status == STATUS_DENIED
                else (
                    "approval_expired"
                    if resolved.status == STATUS_EXPIRED
                    else "approval_cancelled"
                )
            )
            preview = diff_preview_for(tool_name, arguments)
            blocked = json.dumps(
                {
                    "ok": False,
                    "error": reason_code,
                    "approval_id": resolved.id,
                    "tool_name": tool_name,
                    "decision_reason": resolved.decision_reason,
                    "decided_by": resolved.decided_by,
                    "diff_preview": preview,
                    "args_hash": resolved.args_hash,
                },
                ensure_ascii=False,
            )
            if on_tool_event is not None:
                await _emit_tool_event(
                    on_tool_event,
                    {
                        "type": "tool",
                        "phase": "result",
                        "id": event_id,
                        "name": tool_name,
                        "ok": False,
                        "error_code": reason_code,
                        "result": blocked[:20000],
                        "session_id": session_id,
                        "channel": channel,
                        "channel_id": channel_id,
                        "approval_id": resolved.id,
                        "approval_status": resolved.status,
                    },
                )
            return blocked
        # STATUS_APPROVED or STATUS_AWAITING_CONFIRM (defensive): proceed.
    elif not decision.allow and approval_store is None:
        # No store available — block execution rather than bypass.
        reason = (
            decision.reason
            or "approval required but no approval store configured"
        )
        blocked = json.dumps(
            {
                "ok": False,
                "error": "approval_unavailable",
                "message": reason,
                "tool_name": tool_name,
            },
            ensure_ascii=False,
        )
        if on_tool_event is not None:
            await _emit_tool_event(
                on_tool_event,
                {
                    "type": "tool",
                    "phase": "result",
                    "id": event_id,
                    "name": tool_name,
                    "ok": False,
                    "error_code": "approval_unavailable",
                    "result": blocked[:20000],
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                    "approval_status": "unavailable",
                },
            )
        return blocked
    elif decision.source == "always":
        approval_status = "auto_approved"

    if on_tool_event is not None:
        await _emit_tool_event(
            on_tool_event,
            {
                "type": "tool",
                "phase": "start",
                "id": event_id,
                "name": tool_name,
                "arguments": arguments[:4000],
                "session_id": session_id,
                "channel": channel,
                "channel_id": channel_id,
                "approval_id": approval_id,
                "approval_status": approval_status,
            },
        )
    try:
        # Route by registry group; timeout comes from spec default unless
        # the caller passed an explicit override (settings).
        tool_group = group_for(tool_name) or ""
        if tool_group == "filesystem":
            result = dispatch_filesystem_tool(
                tool_name,
                arguments,
                root=workspace_root,
                extra_roots=(tool_offload_dir,) if tool_offload_dir else (),
            )
        elif tool_group == "bash":
            result = await dispatch_bash_tool(
                tool_name,
                arguments,
                root=workspace_root,
                timeout_s=resolve_timeout(tool_name, bash_timeout_s),
            )
        elif tool_group == "git":
            result = await dispatch_git_tool(
                tool_name,
                arguments,
                root=workspace_root,
                timeout_s=resolve_timeout(tool_name, git_timeout_s),
            )
        else:
            # Anything still here is a coding-shaped name we don't own.
            result = json.dumps(
                {
                    "ok": False,
                    "error": "unknown_coding_tool",
                    "tool_name": tool_name,
                    "group": tool_group or None,
                },
                ensure_ascii=False,
            )
    except Exception as exc:  # noqa: BLE001
        result = json.dumps(
            {"ok": False, "error": "tool_exception", "message": str(exc)},
            ensure_ascii=False,
        )
    if approval_id is not None and approval_store is not None:
        try:
            approval_store.mark_consumed(approval_id)
        except Exception:  # noqa: BLE001
            logger.exception("approval mark_consumed failed")
    if on_tool_event is not None:
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            payload = {"ok": False, "error": "invalid_tool_result"}
        await _emit_tool_event(
            on_tool_event,
            {
                "type": "tool",
                "phase": "result",
                "id": event_id,
                "name": tool_name,
                "ok": bool(payload.get("ok")),
                "error_code": payload.get("error"),
                "result": result[:20000],
                "session_id": session_id,
                "channel": channel,
                "channel_id": channel_id,
                "approval_id": approval_id,
                "approval_status": (
                    "approved" if approval_status in {"not_required", "auto_approved"} and approval_id else (
                        approval_status if approval_status != "not_required" else "approved"
                    )
                ),
            },
        )
    return result


async def apply_lazy_skill_tool(
    client: LLMClient,
    request: ChatRequest,
    activation: SkillActivationInfo,
    skills: SkillRuntime | None,
    *,
    session_id: str = "default",
    channel: str = "unknown",
    channel_id: str | None = None,
    schedule_store: ScheduleStore | None = None,
    weather_enabled: bool = False,
    default_city: str | None = None,
    memory: LettaMemoryService | None = None,
    subagent_enabled: bool = True,
    subagent_timeout_s: float = 60.0,
    workspace_root: str = "",
    tool_offload_dir: str = "",
    filesystem_enabled: bool = False,
    bash_enabled: bool = False,
    bash_timeout_s: float = 30.0,
    git_enabled: bool = False,
    git_timeout_s: float = 20.0,
    cancel_event: asyncio.Event | None = None,
    on_subagent_event: OnSubagentEvent | None = None,
    on_tool_event: OnToolEvent | None = None,
    tool_offloader: ToolOffloader | None = None,
    trace_turn_id: str | None = None,
    approval_store: ApprovalStore | None = None,
    effective_policy: EffectivePolicy | None = None,
) -> tuple[ChatRequest, SkillActivationInfo, str | None]:
    """One non-streaming tool round. Returns (request, activation, early_content).

    If the model answers with plain content and no tool call, early_content is set
    and the caller should not stream again.
    Weather / subagent tools inject results and return early_content=None so the
    caller streams a natural-language answer.
    """
    attach_subagent = bool(subagent_enabled) and activation_wants_subagent(
        activation, skills
    )
    tools = _merge_tools(
        activation,
        schedule_store,
        weather_enabled=weather_enabled,
        attach_subagent=attach_subagent,
        filesystem_enabled=filesystem_enabled,
        bash_enabled=bash_enabled,
        git_enabled=git_enabled,
    )
    if not tools:
        return request, activation, None

    probe_request = request
    for _round in range(_MAX_TOOL_ROUNDS):
        probe_req = probe_request.model_copy(
            update={"tools": tools, "tool_choice": "auto"}
        )
        probe: ChatResponse = await client.chat(probe_req)
        coding_calls = [
            tc
            for tc in probe.tool_calls
            if is_coding_tool(tc.name)
            and (
                (filesystem_enabled and tc.name in _FILESYSTEM_TOOL_NAMES)
                or (bash_enabled and tc.name in _BASH_TOOL_NAMES)
                or (git_enabled and tc.name in _GIT_TOOL_NAMES)
            )
        ]
        if not coding_calls:
            break
        messages = list(probe_request.messages)
        executed = False
        for tc in coding_calls:
            result = await _dispatch_coding_tool(
                tc.name,
                tc.arguments,
                call_id=tc.id,
                workspace_root=workspace_root,
                tool_offload_dir=tool_offload_dir,
                filesystem_enabled=filesystem_enabled,
                bash_enabled=bash_enabled,
                bash_timeout_s=bash_timeout_s,
                git_enabled=git_enabled,
                git_timeout_s=git_timeout_s,
                session_id=session_id,
                channel=channel,
                channel_id=channel_id,
                on_tool_event=on_tool_event,
                approval_store=approval_store,
                effective_policy=effective_policy,
                trace_turn_id=trace_turn_id,
                cancel_event=cancel_event,
            )
            if result is None:
                continue
            messages.append(
                await _wrap_tool_result(tool_offloader, tc.name, tc.id, result)
            )
            executed = True
        if not executed:
            break
        probe_request = request.model_copy(update={"messages": messages})
    else:
        messages = list(probe_request.messages)
        messages.append(
            _tool_result_message(
                "tool_runtime",
                json.dumps({"ok": False, "error": "max_tool_rounds_reached"}),
            )
        )
        return _strip_tools(request.model_copy(update={"messages": messages})), activation, None

    if probe_request is not request:
        if not probe.tool_calls and (probe.content or "").strip():
            return _strip_tools(probe_request), activation, probe.content
        return _strip_tools(probe_request), activation, None

    for tc in probe.tool_calls:
        if tc.name == "request_skill" and skills is not None:
            try:
                args = json.loads(tc.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            name = str(args.get("name") or "").strip()
            if not name:
                continue
            logger.info("LAZY request_skill name=%s", name)
            await _emit_tool_event(
                on_tool_event,
                {
                    "type": "tool",
                    "phase": "start",
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments[:4000],
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                },
            )
            new_req, new_act = skills.load_lazy_into_request(
                request, name, activation, session_id=session_id
            )
            await _emit_tool_event(
                on_tool_event,
                {
                    "type": "tool",
                    "phase": "result",
                    "id": tc.id,
                    "name": tc.name,
                    "ok": True,
                    "result": json.dumps({"ok": True, "skill": name}),
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                },
            )
            return _strip_tools(new_req), new_act, None

        if tc.name in _SCHEDULE_TOOL_NAMES and schedule_store is not None:
            sched_decision = resolve_policy(
                effective_policy, tc.name, channel=channel
            )
            sched_approval_id: str | None = None
            sched_approval_status = "not_required"
            if not sched_decision.allow and approval_store is not None:
                async def _sched_approval_emit(ev: dict[str, Any]) -> None:
                    if on_tool_event is None:
                        return
                    await on_tool_event(
                        {
                            "type": "approval_request",
                            "session_id": session_id,
                            "channel": channel,
                            "channel_id": channel_id,
                            **ev,
                        }
                    )

                resolved = await request_approval(
                    approval_store,
                    tool_name=tc.name,
                    arguments=tc.arguments,
                    session_id=session_id,
                    turn_id=trace_turn_id,
                    channel=channel,
                    channel_id=channel_id,
                    requester=f"agent:{trace_turn_id or 'unknown'}",
                    on_event=_sched_approval_emit,
                    cancel_event=cancel_event,
                )
                sched_approval_id = resolved.id
                sched_approval_status = resolved.status
                if resolved.status in {
                    STATUS_DENIED,
                    STATUS_EXPIRED,
                    STATUS_CANCELLED,
                }:
                    reason_code = (
                        "approval_denied"
                        if resolved.status == STATUS_DENIED
                        else (
                            "approval_expired"
                            if resolved.status == STATUS_EXPIRED
                            else "approval_cancelled"
                        )
                    )
                    blocked = json.dumps(
                        {
                            "ok": False,
                            "error": reason_code,
                            "approval_id": resolved.id,
                            "tool_name": tc.name,
                            "decision_reason": resolved.decision_reason,
                            "decided_by": resolved.decided_by,
                        },
                        ensure_ascii=False,
                    )
                    if on_tool_event is not None:
                        await _emit_tool_event(
                            on_tool_event,
                            {
                                "type": "tool",
                                "phase": "result",
                                "id": tc.id,
                                "name": tc.name,
                                "ok": False,
                                "error_code": reason_code,
                                "result": blocked[:20000],
                                "session_id": session_id,
                                "channel": channel,
                                "channel_id": channel_id,
                                "approval_id": resolved.id,
                                "approval_status": resolved.status,
                            },
                        )
                    summary = f"已处理日程工具 {tc.name}：{blocked}"
                    return _strip_tools(request), activation, summary
            elif not sched_decision.allow and approval_store is None:
                blocked = json.dumps(
                    {
                        "ok": False,
                        "error": "approval_unavailable",
                        "tool_name": tc.name,
                    },
                    ensure_ascii=False,
                )
                if on_tool_event is not None:
                    await _emit_tool_event(
                        on_tool_event,
                        {
                            "type": "tool",
                            "phase": "result",
                            "id": tc.id,
                            "name": tc.name,
                            "ok": False,
                            "error_code": "approval_unavailable",
                            "result": blocked[:20000],
                            "session_id": session_id,
                            "channel": channel,
                            "channel_id": channel_id,
                            "approval_status": "unavailable",
                        },
                    )
                summary = f"已处理日程工具 {tc.name}：{blocked}"
                return _strip_tools(request), activation, summary
            elif sched_decision.source == "always":
                sched_approval_status = "auto_approved"

            await _emit_tool_event(
                on_tool_event,
                {
                    "type": "tool",
                    "phase": "start",
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments[:4000],
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                    "approval_id": sched_approval_id,
                    "approval_status": sched_approval_status,
                },
            )
            try:
                result = dispatch_schedule_tool(schedule_store, tc.name, tc.arguments)
                ok = True
                error_code = None
            except Exception as exc:  # noqa: BLE001
                result = json.dumps(
                    {"ok": False, "error": "tool_exception", "message": str(exc)},
                    ensure_ascii=False,
                )
                ok = False
                error_code = "tool_exception"
            if sched_approval_id is not None and approval_store is not None:
                try:
                    approval_store.mark_consumed(sched_approval_id)
                except Exception:  # noqa: BLE001
                    logger.exception("approval mark_consumed failed (schedule)")
            await _emit_tool_event(
                on_tool_event,
                {
                    "type": "tool",
                    "phase": "result",
                    "id": tc.id,
                    "name": tc.name,
                    "ok": ok,
                    "error_code": error_code,
                    "result": str(result)[:20000],
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                    "approval_id": sched_approval_id,
                    "approval_status": sched_approval_status,
                },
            )
            summary = f"已处理日程工具 {tc.name}：{result}"
            return _strip_tools(request), activation, summary

        if tc.name in _WEATHER_TOOL_NAMES and weather_enabled:
            await _emit_tool_event(
                on_tool_event,
                {
                    "type": "tool",
                    "phase": "start",
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments[:4000],
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                },
            )
            try:
                result = await dispatch_weather_tool(
                    tc.name,
                    tc.arguments,
                    default_city=default_city,
                )
                ok = _tool_result_ok(result)
                error_code = None if ok else "tool_failed"
            except Exception as exc:  # noqa: BLE001
                result = json.dumps(
                    {"ok": False, "error": "tool_exception", "message": str(exc)},
                    ensure_ascii=False,
                )
                ok = False
                error_code = "tool_exception"
            await _emit_tool_event(
                on_tool_event,
                {
                    "type": "tool",
                    "phase": "result",
                    "id": tc.id,
                    "name": tc.name,
                    "ok": ok,
                    "error_code": error_code,
                    "result": str(result)[:20000],
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                },
            )
            logger.info("get_weather result_len=%s", len(result))
            messages = list(request.messages)
            messages.append(
                await _wrap_tool_result(tool_offloader, tc.name, tc.id, result)
            )
            enriched = request.model_copy(update={"messages": messages})
            return _strip_tools(enriched), activation, None

        if tc.name == "run_subagent" and attach_subagent:
            await _emit_tool_event(
                on_tool_event,
                {
                    "type": "tool",
                    "phase": "start",
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments[:4000],
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                },
            )
            try:
                result = await dispatch_run_subagent(
                    tc.arguments,
                    llm=client,
                    config=request.config,
                    memory=memory,
                    session_id=session_id,
                    timeout_s=subagent_timeout_s,
                    cancel_event=cancel_event,
                    on_event=on_subagent_event,
                )
                ok = _tool_result_ok(result)
                error_code = None if ok else "tool_failed"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                result = json.dumps(
                    {"ok": False, "error": "tool_exception", "message": str(exc)},
                    ensure_ascii=False,
                )
                ok = False
                error_code = "tool_exception"
            await _emit_tool_event(
                on_tool_event,
                {
                    "type": "tool",
                    "phase": "result",
                    "id": tc.id,
                    "name": tc.name,
                    "ok": ok,
                    "error_code": error_code,
                    "result": str(result)[:20000],
                    "session_id": session_id,
                    "channel": channel,
                    "channel_id": channel_id,
                },
            )
            logger.info("run_subagent result_len=%s", len(result))
            messages = list(request.messages)
            messages.append(
                await _wrap_tool_result(tool_offloader, tc.name, tc.id, result)
            )
            enriched = request.model_copy(update={"messages": messages})
            return _strip_tools(enriched), activation, None

    if (probe.content or "").strip():
        return _strip_tools(request), activation, probe.content
    return _strip_tools(request), activation, None


async def stream_assistant_turn(
    client: LLMClient,
    request: ChatRequest,
    activation: SkillActivationInfo,
    skills: SkillRuntime | None,
    *,
    session_id: str = "default",
    channel: str = "unknown",
    channel_id: str | None = None,
    schedule_store: ScheduleStore | None = None,
    weather_enabled: bool = False,
    default_city: str | None = None,
    on_schedule_mutated: Callable[[], None] | None = None,
    memory: LettaMemoryService | None = None,
    subagent_enabled: bool = True,
    subagent_timeout_s: float = 60.0,
    workspace_root: str = "",
    tool_offload_dir: str = "",
    filesystem_enabled: bool = False,
    bash_enabled: bool = False,
    bash_timeout_s: float = 30.0,
    git_enabled: bool = False,
    git_timeout_s: float = 20.0,
    cancel_event: asyncio.Event | None = None,
    on_subagent_event: OnSubagentEvent | None = None,
    on_tool_event: OnToolEvent | None = None,
    tool_offloader: ToolOffloader | None = None,
    trace_turn_id: str | None = None,
    approval_store: ApprovalStore | None = None,
    effective_policy: EffectivePolicy | None = None,
) -> AsyncIterator[tuple[str, SkillActivationInfo]]:
    """Yield (token, activation). First yield may update activation after tools."""
    act = activation
    req = request
    early: str | None = None
    attach_subagent = bool(subagent_enabled) and activation_wants_subagent(
        act, skills
    )
    tools = _merge_tools(
        act,
        schedule_store,
        weather_enabled=weather_enabled,
        attach_subagent=attach_subagent,
        filesystem_enabled=filesystem_enabled,
        bash_enabled=bash_enabled,
        git_enabled=git_enabled,
    )
    if tools:
        act = SkillActivationInfo(
            active=act.active,
            lazy_catalog=act.lazy_catalog,
            scores=act.scores,
            tools=tools,
        )
        req, act, early = await apply_lazy_skill_tool(
            client,
            req,
            act,
            skills,
            session_id=session_id,
            channel=channel,
            channel_id=channel_id,
            schedule_store=schedule_store,
            weather_enabled=weather_enabled,
            default_city=default_city,
            memory=memory,
            subagent_enabled=subagent_enabled,
            tool_offloader=tool_offloader,
            subagent_timeout_s=subagent_timeout_s,
            workspace_root=workspace_root,
            tool_offload_dir=tool_offload_dir,
            filesystem_enabled=filesystem_enabled,
            bash_enabled=bash_enabled,
            bash_timeout_s=bash_timeout_s,
            git_enabled=git_enabled,
            git_timeout_s=git_timeout_s,
            cancel_event=cancel_event,
            on_subagent_event=on_subagent_event,
            on_tool_event=on_tool_event,
            trace_turn_id=trace_turn_id,
            approval_store=approval_store,
            effective_policy=effective_policy,
        )
        if early is not None and on_schedule_mutated is not None:
            if "日程工具" in early:
                on_schedule_mutated()

    if early is not None:
        step = max(1, len(early) // 12)
        for i in range(0, len(early), step):
            yield early[i : i + step], act
        return

    async for token in client.stream(_strip_tools(req)):
        yield token, act
