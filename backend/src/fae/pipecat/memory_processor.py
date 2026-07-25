"""Pipecat helpers + processor: seed + persist turns via LettaMemoryService."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fae.chat_history import ChatHistoryStore

if TYPE_CHECKING:
    from fae.agent.skills_runtime import SkillRuntime
    from fae.pipecat.services.letta_memory import LettaMemoryService

logger = logging.getLogger("fae.pipecat.memory_processor")


async def seed_daily_memory(
    *,
    memory: LettaMemoryService | None,
    session_id: str,
    add_message: Any,
    skills: Any | None = None,
) -> str:
    """Recall memories (+ optional skills) and push system messages into LLMContext.

    Skill seed uses empty user text → always_on + lazy catalog only (no trigger match).
    `add_message` is `LLMContext.add_message`. Returns the memory text used.
    """
    memory_text = ""
    if memory is not None and memory.enabled:
        try:
            memory_text = await memory.recall_context("", session_id=session_id)
        except Exception:  # noqa: BLE001
            logger.exception("Daily memory seed failed")
            memory_text = ""
        msg = memory.memory_system_message(memory_text)
        if msg is not None:
            add_message(msg)

    if skills is not None and getattr(skills, "enabled", False):
        try:
            skill_msg = skills.system_message_dict(
                "", session_id, record_trigger=False
            )
            if skill_msg is not None:
                add_message(skill_msg)
        except Exception:  # noqa: BLE001
            logger.exception("Daily skills seed failed")
    return memory_text


def build_skills_turn_processor(
    skills: SkillRuntime | None,
    session_id: str,
    context: Any,
) -> Any | None:
    """Rematch trigger skills on each finalized user transcript (Daily path)."""
    if skills is None or not getattr(skills, "enabled", False):
        return None

    from pipecat.frames.frames import Frame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    class SkillsTurnProcessor(FrameProcessor):
        def __init__(self) -> None:
            super().__init__()

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame):
                text = (frame.text or "").strip()
                finalized = bool(getattr(frame, "finalized", True))
                if text and finalized:
                    try:
                        active = skills.refresh_context_skills(
                            context, text, session_id=session_id
                        )
                        logger.info(
                            "Daily skills rematch session=%s active=%s",
                            session_id,
                            active,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("Daily skills rematch failed")
            await self.push_frame(frame, direction)

    return SkillsTurnProcessor()


async def persist_daily_turn(
    *,
    memory: LettaMemoryService | None,
    session_id: str,
    user_text: str,
    assistant_text: str,
    chat_history_store: ChatHistoryStore | None = None,
) -> None:
    if not (user_text or "").strip():
        return
    if (
        chat_history_store is not None
        and not chat_history_store.closed
    ):
        try:
            chat_history_store.append(
                session_id, user_text, assistant_text or "",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Daily chat history persist failed")
    if memory is None or not memory.enabled:
        return
    try:
        await memory.persist_turn(
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text or "",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Daily persist_turn failed")


def build_memory_turn_processor(
    memory: LettaMemoryService | None,
    session_id: str,
    *,
    chat_history_store: ChatHistoryStore | None = None,
) -> Any | None:
    """Return a FrameProcessor that persists completed LLM turns, or None.

    A processor is returned whenever either memory or chat_history_store can
    accept writes — memory is optional, history persists regardless.
    """
    has_memory = memory is not None and memory.enabled
    has_history = (
        chat_history_store is not None and not chat_history_store.closed
    )
    if not has_memory and not has_history:
        return None

    from pipecat.frames.frames import (
        Frame,
        InterimTranscriptionFrame,
        LLMFullResponseEndFrame,
        LLMFullResponseStartFrame,
        LLMTextFrame,
        TranscriptionFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    class MemoryTurnProcessor(FrameProcessor):
        def __init__(self) -> None:
            super().__init__()
            self._user = ""
            self._assistant_parts: list[str] = []

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame):
                text = (frame.text or "").strip()
                # Prefer finalized transcripts; allow first non-empty as bootstrap.
                if text and (getattr(frame, "finalized", False) or not self._user):
                    self._user = text
            elif isinstance(frame, InterimTranscriptionFrame):
                # Ignore interim — wait for final TranscriptionFrame.
                pass
            elif isinstance(frame, LLMFullResponseStartFrame):
                self._assistant_parts = []
            elif isinstance(frame, LLMTextFrame):
                if frame.text:
                    self._assistant_parts.append(frame.text)
            elif isinstance(frame, LLMFullResponseEndFrame):
                assistant = "".join(self._assistant_parts).strip()
                user = self._user
                # Clear turn state so the next user utterance cannot reuse this one.
                self._assistant_parts = []
                self._user = ""
                if user:
                    await persist_daily_turn(
                        memory=memory,
                        session_id=session_id,
                        user_text=user,
                        assistant_text=assistant,
                        chat_history_store=chat_history_store,
                    )
            await self.push_frame(frame, direction)

    return MemoryTurnProcessor()
