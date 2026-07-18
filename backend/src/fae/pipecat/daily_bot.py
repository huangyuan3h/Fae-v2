"""Full Pipecat voice bot for Daily WebRTC (Phase 1 enhanced path).

Pipeline:
  Daily in → Silero VAD / SmartTurn → OpenAI-compatible STT (ASR URL)
  → LLM (DashScope-compatible) → DashScope TTS → Daily out
"""

from __future__ import annotations

import logging

from fae.config import Settings

logger = logging.getLogger("fae.pipecat.daily_bot")


async def run_daily_bot(
    *,
    room_url: str,
    token: str,
    settings: Settings,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
) -> None:
    """Join a Daily room and run the voice pipeline until the call ends."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.frames.frames import EndFrame, LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.openai.stt import OpenAISTTService
    from pipecat.transports.daily.transport import DailyParams, DailyTransport
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    from fae.pipecat.services.dashscope_tts import DashScopeTTSService

    api_key = llm_api_key or settings.dashscope_api_key
    base_url = llm_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model = llm_model or "qwen3-max"
    asr_url = settings.vllm_asr_url.rstrip("/")

    transport = DailyTransport(
        room_url,
        token,
        "FAE",
        DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    stt = OpenAISTTService(
        api_key=api_key or "asr-stub",
        base_url=asr_url,
        model="whisper-1",
    )
    llm = OpenAILLMService(
        api_key=api_key,
        base_url=base_url,
        settings=OpenAILLMService.Settings(
            model=model,
            system_instruction=(
                "You are FAE, a concise bilingual voice assistant. "
                "Keep replies short and conversational."
            ),
        ),
    )
    tts = DashScopeTTSService(api_key=settings.dashscope_api_key or api_key or "")

    context = LLMContext()
    # Silero VAD + default UserTurnStrategies (stop uses LocalSmartTurnAnalyzerV3).
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            user_turn_strategies=UserTurnStrategies(),
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_agg,
            llm,
            tts,
            transport.output(),
            assistant_agg,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):  # noqa: ANN001
        logger.info("Participant joined: %s", participant.get("id"))
        context.add_message(
            {
                "role": "system",
                "content": "Greet the user briefly in Chinese.",
            }
        )
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):  # noqa: ANN001
        logger.info("Participant left (%s)", reason)
        await task.queue_frame(EndFrame())

    @transport.event_handler("on_call_state_updated")
    async def on_call_state_updated(transport, state):  # noqa: ANN001
        if state == "left":
            await task.queue_frame(EndFrame())

    runner = PipelineRunner()
    await runner.run(task)
