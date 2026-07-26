"""Shared chat request preparation: memory → context → skills."""

from __future__ import annotations

import logging

from fae.agent.skills_runtime import SkillActivationInfo, SkillRuntime
from fae.llm.types import ChatRequest
from fae.memory.core_budget import (
    clip_recent_turns_for_budget,
    estimate_tokens,
)
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.tools.context import (
    build_context_block,
    inject_context,
    resolve_location_defaults,
)

logger = logging.getLogger("fae.agent.prepare")


async def prepare_chat_request(
    body: ChatRequest,
    *,
    session_id: str,
    memory: LettaMemoryService | None,
    skills: SkillRuntime | None,
    default_city: str = "",
    default_timezone: str = "",
    context_window_tokens: int | None = None,
    reserve_tokens: int | None = None,
) -> tuple[ChatRequest, SkillActivationInfo, str | None]:
    """Memory inject → runtime context → skills inject.

    Returns (prepared, activation, resolved_default_city).

    When ``context_window_tokens`` is provided, the memory block is soft
    clipped so the system prompt + reserved completion fits inside the
    model window. ``reserve_tokens`` defaults to 2048.
    """
    prepared = body
    user_text = ""
    for msg in reversed(body.messages):
        if msg.role == "user":
            user_text = msg.content
            break

    cfg_window = getattr(body.config, "context_window", None) or context_window_tokens
    budget_chars: int | None = None
    if cfg_window is not None:
        reserve = reserve_tokens if reserve_tokens is not None else 2048
        budget_chars = max(256, (cfg_window - reserve) * 4)

    city, timezone = await resolve_location_defaults(
        memory,
        env_city=default_city,
        env_timezone=default_timezone,
    )
    human_block = ""
    if memory is not None and memory.enabled and memory.client is not None:
        try:
            human_block = await memory.client.get_block("human")
        except Exception:  # noqa: BLE001
            human_block = ""

    if memory is not None and memory.enabled:
        if budget_chars is not None:
            prepared = await memory.prepare_request(
                prepared, session_id=session_id, char_budget=budget_chars,
            )
        else:
            prepared = await memory.prepare_request(prepared, session_id=session_id)

    if budget_chars is not None:
        sys_chars = sum(len(m.content) for m in prepared.messages if m.role == "system")
        budget_tokens = budget_chars // 4
        if sys_chars > budget_chars:
            logger.warning(
                "system prompt %d chars exceeds budget %d; soft-trimming",
                sys_chars, budget_chars,
            )
            for idx, msg in enumerate(prepared.messages):
                if msg.role != "system":
                    continue
                msg_tokens = estimate_tokens(msg.content)
                if msg_tokens <= budget_tokens:
                    continue
                clipped = clip_recent_turns_for_budget(
                    msg.content, char_budget=budget_chars,
                )
                prepared.messages[idx] = msg.model_copy(update={"content": clipped})

    context = build_context_block(
        human_block=human_block,
        city=city,
        timezone=timezone,
    )
    prepared = inject_context(prepared, context)

    activation = SkillActivationInfo()
    if skills is not None and skills.enabled:
        prepared, activation = skills.prepare_request(
            prepared, session_id=session_id, user_text=user_text
        )
    return prepared, activation, city
