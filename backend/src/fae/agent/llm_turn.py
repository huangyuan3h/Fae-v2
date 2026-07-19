"""Run one assistant turn with optional LAZY request_skill tool round."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fae.agent.skills_runtime import SkillActivationInfo, SkillRuntime
from fae.llm.client import LLMClient
from fae.llm.types import ChatRequest, ChatResponse

logger = logging.getLogger("fae.agent.skills")


def _strip_tools(request: ChatRequest) -> ChatRequest:
    if request.tools is None and request.tool_choice is None:
        return request
    return request.model_copy(update={"tools": None, "tool_choice": None})


async def apply_lazy_skill_tool(
    client: LLMClient,
    request: ChatRequest,
    activation: SkillActivationInfo,
    skills: SkillRuntime,
    *,
    session_id: str = "default",
) -> tuple[ChatRequest, SkillActivationInfo, str | None]:
    """One non-streaming tool round. Returns (request, activation, early_content).

    If the model answers with plain content and no tool call, early_content is set
    and the caller should not stream again.
    """
    if not activation.tools:
        return request, activation, None

    probe_req = request.model_copy(
        update={"tools": activation.tools, "tool_choice": "auto"}
    )
    probe: ChatResponse = await client.chat(probe_req)
    for tc in probe.tool_calls:
        if tc.name != "request_skill":
            continue
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
) -> AsyncIterator[tuple[str, SkillActivationInfo]]:
    """Yield (token, activation). First yield may update activation after LAZY."""
    act = activation
    req = request
    early: str | None = None
    if skills is not None and act.tools:
        req, act, early = await apply_lazy_skill_tool(
            client, req, act, skills, session_id=session_id
        )
        # Emit a zero-width marker token path: caller sees updated activation
        # via the paired activation on each yield.
    if early is not None:
        # Chunk early content so WS clients still get progressive tokens.
        step = max(1, len(early) // 12)
        for i in range(0, len(early), step):
            yield early[i : i + step], act
        return

    async for token in client.stream(_strip_tools(req)):
        yield token, act
