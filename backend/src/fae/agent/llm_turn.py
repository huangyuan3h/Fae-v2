"""Run one assistant turn with optional LAZY request_skill + tools."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fae.agent.skills_runtime import SkillActivationInfo, SkillRuntime
from fae.agent.subagents.tools import RUN_SUBAGENT_TOOL, dispatch_run_subagent
from fae.llm.client import LLMClient
from fae.llm.types import ChatMessage, ChatRequest, ChatResponse
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.scheduler.tools import SCHEDULE_TOOLS, dispatch_schedule_tool
from fae.tools.bash import BASH_TOOLS, dispatch_bash_tool
from fae.tools.filesystem import FILESYSTEM_TOOLS, dispatch_filesystem_tool
from fae.tools.git import GIT_TOOLS, dispatch_git_tool
from fae.tools.weather import WEATHER_TOOLS, dispatch_weather_tool

if TYPE_CHECKING:
    from fae.scheduler.store import ScheduleStore

logger = logging.getLogger("fae.agent.skills")

_MAX_TOOL_ROUNDS = 6

_SCHEDULE_TOOL_NAMES = {
    "schedule_create_job",
    "list_jobs",
    "cancel_job",
}

_WEATHER_TOOL_NAMES = {"get_weather"}
_FILESYSTEM_TOOL_NAMES = {"read_file", "search_files", "write_file", "edit_file"}
_BASH_TOOL_NAMES = {"run_bash"}
_GIT_TOOL_NAMES = {"git_status", "git_diff", "git_log"}

OnSubagentEvent = Callable[[dict[str, Any]], Awaitable[None]]


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
    tools = list(activation.tools or [])
    if schedule_store is not None:
        _append_unique_tools(tools, SCHEDULE_TOOLS)
    if weather_enabled:
        _append_unique_tools(tools, WEATHER_TOOLS)
    if attach_subagent:
        _append_unique_tools(tools, [RUN_SUBAGENT_TOOL])
    if filesystem_enabled:
        _append_unique_tools(tools, FILESYSTEM_TOOLS)
    if bash_enabled:
        _append_unique_tools(tools, BASH_TOOLS)
    if git_enabled:
        _append_unique_tools(tools, GIT_TOOLS)
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


async def _dispatch_coding_tool(
    tool_name: str,
    arguments: str,
    *,
    workspace_root: str,
    filesystem_enabled: bool,
    bash_enabled: bool,
    bash_timeout_s: float,
    git_enabled: bool,
    git_timeout_s: float,
) -> str | None:
    if tool_name in _FILESYSTEM_TOOL_NAMES and filesystem_enabled:
        return dispatch_filesystem_tool(tool_name, arguments, root=workspace_root)
    if tool_name in _BASH_TOOL_NAMES and bash_enabled:
        return await dispatch_bash_tool(
            tool_name,
            arguments,
            root=workspace_root,
            timeout_s=bash_timeout_s,
        )
    if tool_name in _GIT_TOOL_NAMES and git_enabled:
        return await dispatch_git_tool(
            tool_name,
            arguments,
            root=workspace_root,
            timeout_s=git_timeout_s,
        )
    return None


async def apply_lazy_skill_tool(
    client: LLMClient,
    request: ChatRequest,
    activation: SkillActivationInfo,
    skills: SkillRuntime | None,
    *,
    session_id: str = "default",
    schedule_store: ScheduleStore | None = None,
    weather_enabled: bool = False,
    default_city: str | None = None,
    memory: LettaMemoryService | None = None,
    subagent_enabled: bool = True,
    subagent_timeout_s: float = 60.0,
    workspace_root: str = "",
    filesystem_enabled: bool = False,
    bash_enabled: bool = False,
    bash_timeout_s: float = 30.0,
    git_enabled: bool = False,
    git_timeout_s: float = 20.0,
    cancel_event: asyncio.Event | None = None,
    on_subagent_event: OnSubagentEvent | None = None,
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
            if tc.name in _FILESYSTEM_TOOL_NAMES | _BASH_TOOL_NAMES | _GIT_TOOL_NAMES
        ]
        if not coding_calls:
            break
        messages = list(probe_request.messages)
        executed = False
        for tc in coding_calls:
            result = await _dispatch_coding_tool(
                tc.name,
                tc.arguments,
                workspace_root=workspace_root,
                filesystem_enabled=filesystem_enabled,
                bash_enabled=bash_enabled,
                bash_timeout_s=bash_timeout_s,
                git_enabled=git_enabled,
                git_timeout_s=git_timeout_s,
            )
            if result is None:
                continue
            messages.append(_tool_result_message(tc.name, result))
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
            new_req, new_act = skills.load_lazy_into_request(
                request, name, activation, session_id=session_id
            )
            return _strip_tools(new_req), new_act, None

        if tc.name in _SCHEDULE_TOOL_NAMES and schedule_store is not None:
            result = dispatch_schedule_tool(schedule_store, tc.name, tc.arguments)
            summary = f"已处理日程工具 {tc.name}：{result}"
            return _strip_tools(request), activation, summary

        if tc.name in _WEATHER_TOOL_NAMES and weather_enabled:
            result = await dispatch_weather_tool(
                tc.name,
                tc.arguments,
                default_city=default_city,
            )
            logger.info("get_weather result_len=%s", len(result))
            messages = list(request.messages)
            messages.append(_tool_result_message(tc.name, result))
            enriched = request.model_copy(update={"messages": messages})
            return _strip_tools(enriched), activation, None

        if tc.name == "run_subagent" and attach_subagent:
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
            logger.info("run_subagent result_len=%s", len(result))
            messages = list(request.messages)
            messages.append(_tool_result_message(tc.name, result))
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
    schedule_store: ScheduleStore | None = None,
    weather_enabled: bool = False,
    default_city: str | None = None,
    on_schedule_mutated: Callable[[], None] | None = None,
    memory: LettaMemoryService | None = None,
    subagent_enabled: bool = True,
    subagent_timeout_s: float = 60.0,
    workspace_root: str = "",
    filesystem_enabled: bool = False,
    bash_enabled: bool = False,
    bash_timeout_s: float = 30.0,
    git_enabled: bool = False,
    git_timeout_s: float = 20.0,
    cancel_event: asyncio.Event | None = None,
    on_subagent_event: OnSubagentEvent | None = None,
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
            schedule_store=schedule_store,
            weather_enabled=weather_enabled,
            default_city=default_city,
            memory=memory,
            subagent_enabled=subagent_enabled,
            subagent_timeout_s=subagent_timeout_s,
            workspace_root=workspace_root,
            filesystem_enabled=filesystem_enabled,
            bash_enabled=bash_enabled,
            bash_timeout_s=bash_timeout_s,
            git_enabled=git_enabled,
            git_timeout_s=git_timeout_s,
            cancel_event=cancel_event,
            on_subagent_event=on_subagent_event,
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
