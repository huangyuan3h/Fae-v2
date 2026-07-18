"""Pipecat helpers + processor: seed + persist turns via LettaMemoryService."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fae.pipecat.services.letta_memory import LettaMemoryService

logger = logging.getLogger("fae.pipecat.memory_processor")


async def seed_daily_memory(
    *,
    memory: LettaMemoryService | None,
    session_id: str,
    add_message: Any,
) -> str:
    """Recall memories and push a system message into LLMContext.

    `add_message` is `LLMContext.add_message`. Returns the memory text used.
    """
    if memory is None or not memory.enabled:
        return ""
    try:
        text = await memory.recall_context("", session_id=session_id)
    except Exception:  # noqa: BLE001
        logger.exception("Daily memory seed failed")
        return ""
    msg = memory.memory_system_message(text)
    if msg is not None:
        add_message(msg)
    return text


async def persist_daily_turn(
    *,
    memory: LettaMemoryService | None,
    session_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    if memory is None or not memory.enabled:
        return
    if not (user_text or "").strip():
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
) -> Any | None:
    """Return a FrameProcessor that persists completed LLM turns, or None."""
    if memory is None or not memory.enabled:
        return None

    from pipecat.frames.frames import (
        Frame,
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
                if text and (frame.finalized or not self._user):
                    self._user = text
            elif isinstance(frame, LLMFullResponseStartFrame):
                self._assistant_parts = []
            elif isinstance(frame, LLMTextFrame):
                if frame.text:
                    self._assistant_parts.append(frame.text)
            elif isinstance(frame, LLMFullResponseEndFrame):
                assistant = "".join(self._assistant_parts).strip()
                user = self._user
                self._assistant_parts = []
                if user:
                    await persist_daily_turn(
                        memory=memory,
                        session_id=session_id,
                        user_text=user,
                        assistant_text=assistant,
                    )
            await self.push_frame(frame, direction)

    return MemoryTurnProcessor()