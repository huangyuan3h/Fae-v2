"""Shared chat request preparation: memory → context → skills."""

from __future__ import annotations

from fae.agent.skills_runtime import SkillActivationInfo, SkillRuntime
from fae.llm.types import ChatRequest
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.tools.context import (
    build_context_block,
    inject_context,
    resolve_location_defaults,
)


async def prepare_chat_request(
    body: ChatRequest,
    *,
    session_id: str,
    memory: LettaMemoryService | None,
    skills: SkillRuntime | None,
    default_city: str = "",
    default_timezone: str = "",
) -> tuple[ChatRequest, SkillActivationInfo, str | None]:
    """Memory inject → runtime context → skills inject.

    Returns (prepared, activation, resolved_default_city).
    """
    prepared = body
    user_text = ""
    for msg in reversed(body.messages):
        if msg.role == "user":
            user_text = msg.content
            break

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
        prepared = await memory.prepare_request(prepared, session_id=session_id)

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
