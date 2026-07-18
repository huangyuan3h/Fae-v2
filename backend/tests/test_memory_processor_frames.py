"""Drive MemoryTurnProcessor with Pipecat frames."""

from __future__ import annotations

from pathlib import Path

import pytest
from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from fae.memory.embedded import EmbeddedMemoryClient
from fae.pipecat.memory_processor import build_memory_turn_processor
from fae.pipecat.services.letta_memory import LettaMemoryService


@pytest.mark.asyncio
async def test_memory_turn_processor_persists_on_llm_end(tmp_path: Path) -> None:
    client = EmbeddedMemoryClient(tmp_path / "proc.db")
    await client.ensure_agent()
    service = LettaMemoryService(client)
    proc = build_memory_turn_processor(service, "p1")
    assert proc is not None

    await proc.process_frame(
        TranscriptionFrame(text="聊聊 Python", user_id="u", timestamp="0"),
        FrameDirection.DOWNSTREAM,
    )
    # Mark finalized so user text sticks
    await proc.process_frame(
        TranscriptionFrame(
            text="聊聊 Python", user_id="u", timestamp="1", finalized=True
        ),
        FrameDirection.DOWNSTREAM,
    )
    await proc.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await proc.process_frame(LLMTextFrame(text="好的"), FrameDirection.DOWNSTREAM)
    await proc.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    turns = await client.list_recall("p1")
    assert turns
    assert "Python" in turns[0].user_text
    assert "好的" in turns[0].assistant_text
    await client.close()
