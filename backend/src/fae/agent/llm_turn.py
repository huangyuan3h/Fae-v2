"""Run one assistant turn with optional LAZY request_skill + schedule tools."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from fae.agent.skills_runtime import SkillActivationInfo, SkillRuntime
from fae.llm.client import LLMClient
from fae.llm.types import ChatRequest, ChatResponse
from fae.scheduler.tools import SCHEDULE_TOOLS, dispatch_schedule_tool

if TYPE_CHECKING:
    from fae.scheduler.store import ScheduleStore

logger = logging.getLogger("fae.agent.skills")

_SCHEDULE_TOOL_NAMES = {
    "schedule_create_job",
    "list_jobs",
    "cancel_job",
}


def _strip_tools(request: ChatRequest) -> ChatRequest:
    if request.tools is None and request.tool_choice is None:
        return request
    return request.model_copy(update={"tools": None, "tool_choice": None})


def _merge_tools(
    activation: SkillActivationInfo,
    schedule_store: ScheduleStore | None,
) -> list[dict]:
    tools = list(activation.tools or [])
    if schedule_store is not None:
        names = {
            t.get("function", {}).get("name")
            for t in tools
            if isinstance(t, dict)
        }
        for t in SCHEDULE_TOOLS:
            n = t.get("function", {}).get("name")
            if n not in names:
                tools.append(t)
    return tools


async def apply_lazy_skill_tool(
    client: LLMClient,
    request: ChatRequest,
    activation: SkillActivationInfo,
    skills: SkillRuntime | None,
    *,
    session_id: str = "default",
    schedule_store: ScheduleStore | None = None,
) -> tuple[ChatRequest, SkillActivationInfo, str | None]:
    """One non-streaming tool round. Returns (request, activation, early_content).

    If the model answers with plain content and no tool call, early_content is set
    and the caller should not stream again.
    """
    tools = _merge_tools(activation, schedule_store)
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
    on_schedule_mutated: Callable[[], None] | None = None,
) -> AsyncIterator[tuple[str, SkillActivationInfo]]:
    """Yield (token, activation). First yield may update activation after tools."""
    act = activation
    req = request
    early: str | None = None
    tools = _merge_tools(act, schedule_store)
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
