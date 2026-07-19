"""Shared chat request preparation: memory then skills."""

from __future__ import annotations

from fae.agent.skills_runtime import SkillActivationInfo, SkillRuntime
from fae.llm.types import ChatRequest
from fae.pipecat.services.letta_memory import LettaMemoryService


async def prepare_chat_request(
    body: ChatRequest,
    *,
    session_id: str,
    memory: LettaMemoryService | None,
    skills: SkillRuntime | None,
) -> tuple[ChatRequest, SkillActivationInfo]:
    """Memory inject → skills inject. Returns prepared request + activation."""
    prepared = body
    user_text = ""
    for msg in reversed(body.messages):
        if msg.role == "user":
            user_text = msg.content
            break

    if memory is not None and memory.enabled:
        prepared = await memory.prepare_request(prepared, session_id=session_id)

    activation = SkillActivationInfo()
    if skills is not None and skills.enabled:
        prepared, activation = skills.prepare_request(
            prepared, session_id=session_id, user_text=user_text
        )
    return prepared, activation
