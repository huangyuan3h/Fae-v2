"""Run one assistant turn with optional LAZY request_skill + tools."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from fae.agent.skills_runtime import SkillActivationInfo, SkillRuntime
from fae.llm.client import LLMClient
from fae.llm.types import ChatMessage, ChatRequest, ChatResponse
from fae.scheduler.tools import SCHEDULE_TOOLS, dispatch_schedule_tool
from fae.tools.weather import WEATHER_TOOLS, dispatch_weather_tool

if TYPE_CHECKING:
    from fae.scheduler.store import ScheduleStore

logger = logging.getLogger("fae.agent.skills")

_SCHEDULE_TOOL_NAMES = {
    "schedule_create_job",
    "list_jobs",
    "cancel_job",
}

_WEATHER_TOOL_NAMES = {"get_weather"}


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


def _merge_tools(
    activation: SkillActivationInfo,
    schedule_store: ScheduleStore | None,
    *,
    weather_enabled: bool = False,
) -> list[dict]:
    tools = list(activation.tools or [])
    if schedule_store is not None:
        _append_unique_tools(tools, SCHEDULE_TOOLS)
    if weather_enabled:
        _append_unique_tools(tools, WEATHER_TOOLS)
    return tools


def _tool_result_message(tool_name: str, result: str) -> ChatMessage:
    return ChatMessage(
        role="system",
        content=(
            f'<tool_result name="{tool_name}">\n{result}\n</tool_result>\n'
            "Use this live tool data to answer the user. "
            "Do not claim you lack access to this information."
        ),
    )


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
) -> tuple[ChatRequest, SkillActivationInfo, str | None]:
    """One non-streaming tool round. Returns (request, activation, early_content).

    If the model answers with plain content and no tool call, early_content is set
    and the caller should not stream again.
    Weather tools inject results and return early_content=None so the caller
    streams a natural-language answer.
    """
    tools = _merge_tools(
        activation, schedule_store, weather_enabled=weather_enabled
    )
    if not tools:
        return request, activation, None

    probe_req = request.model_copy(update={"tools": tools, "tool_choice": "auto"})
    probe: ChatResponse = await client.chat(probe_req)

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
) -> AsyncIterator[tuple[str, SkillActivationInfo]]:
    """Yield (token, activation). First yield may update activation after tools."""
    act = activation
    req = request
    early: str | None = None
    tools = _merge_tools(act, schedule_store, weather_enabled=weather_enabled)
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
