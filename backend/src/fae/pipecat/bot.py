"""Text-mode pipeline bot (Phase 1.3 minimal attempt).

Assembles: user text → LLM stream → SentenceAggregator → TTS stub → transport
with barge-in support. Full mic→VAD→ASR path waits for Daily transport + UI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from fae.llm import LLMClient, LLMConfig
from fae.pipecat.barge_in import BargeInController
from fae.pipecat.sentence import SentenceAggregator
from fae.pipecat.services.qwen3_llm import Qwen3LLMService
from fae.pipecat.services.qwen3_tts import Qwen3TTSService
from fae.pipecat.transport import LocalTransport, VoiceTransport

EventType = Literal["token", "sentence", "audio", "done", "interrupted", "error"]


@dataclass(frozen=True)
class PipelineEvent:
    type: EventType
    content: str | None = None
    audio: bytes | None = None
    meta: dict[str, Any] | None = None


class TextPipelineBot:
    """Run one assistant turn over text with streaming + sentence TTS hooks."""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        tts: Qwen3TTSService | None = None,
        transport: VoiceTransport | None = None,
        system_prompt: str | None = "You are FAE, a concise voice assistant.",
    ) -> None:
        self._llm = Qwen3LLMService(llm_client)
        self._tts = tts or Qwen3TTSService()
        self._transport = transport or LocalTransport()
        self._system_prompt = system_prompt
        self.barge_in = BargeInController()

    async def run_turn(
        self, user_text: str, config: LLMConfig
    ) -> AsyncIterator[PipelineEvent]:
        """Stream pipeline events for a single user utterance."""
        aggregator = SentenceAggregator()
        self.barge_in.reset()
        self.barge_in.start_playback()

        try:
            async for token in self._llm.stream_reply(
                user_text=user_text,
                config=config,
                system_prompt=self._system_prompt,
            ):
                if self.barge_in.interrupted:
                    yield PipelineEvent(type="interrupted")
                    return

                yield PipelineEvent(type="token", content=token)

                for sentence in aggregator.push(token):
                    if self.barge_in.interrupted:
                        yield PipelineEvent(type="interrupted")
                        return
                    async for ev in self._emit_sentence(sentence):
                        yield ev

            leftover = aggregator.flush()
            if leftover and not self.barge_in.interrupted:
                async for ev in self._emit_sentence(leftover):
                    yield ev

            yield PipelineEvent(type="done")
        except Exception as e:  # noqa: BLE001
            yield PipelineEvent(
                type="error",
                content=str(e),
                meta={"code": getattr(e, "code", "unknown")},
            )
        finally:
            self.barge_in.stop_playback()

    async def _emit_sentence(self, sentence: str) -> AsyncIterator[PipelineEvent]:
        yield PipelineEvent(type="sentence", content=sentence)
        await self._transport.send_assistant_text(sentence)
        pcm = await self._tts.synthesize(sentence)
        if pcm:
            await self._transport.send_assistant_audio(pcm)
            yield PipelineEvent(type="audio", content=sentence, audio=pcm)
