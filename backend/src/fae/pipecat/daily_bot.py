"""Full Pipecat voice bot for Daily WebRTC (Phase 1 enhanced path).

Pipeline:
  Daily in → Silero VAD / SmartTurn → OpenAI-compatible STT (ASR URL)
  → LLM (OpenAI-compatible) → Local TTS → Daily out
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fae.chat_history import ChatHistoryStore
from fae.config import Settings
from fae.pipecat.memory_processor import (
    build_memory_turn_processor,
    build_skills_turn_processor,
    seed_daily_memory,
)
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.pipecat.summarizer_bridge import build_assistant_aggregator_params

logger = logging.getLogger("fae.pipecat.daily_bot")

InterruptFn = Callable[[], Awaitable[None]]
ReadyFn = Callable[[InterruptFn], None]


async def run_daily_bot(
    *,
    room_url: str,
    token: str,
    settings: Settings,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
    on_ready: ReadyFn | None = None,
    memory: LettaMemoryService | None = None,
    session_id: str | None = None,
    skills: object | None = None,
    chat_history_store: ChatHistoryStore | None = None,
) -> None:
    """Join a Daily room and run the voice pipeline until the call ends."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.frames.frames import EndFrame, InterruptionFrame, LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMAssistantAggregatorParams,
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.openai.stt import OpenAISTTService
    from pipecat.transports.daily.transport import DailyParams, DailyTransport
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    from fae.pipecat.services.local_tts_service import LocalTTSService

    api_key = llm_api_key or settings.dashscope_api_key
    base_url = llm_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model = llm_model or "qwen3-max"
    asr_url = settings.vllm_asr_url.rstrip("/")
    sid = session_id or "daily"

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

    from fae.memory.defaults import DEFAULT_PERSONA

    persona_text = DEFAULT_PERSONA
    if memory is not None and memory.enabled and memory.client is not None:
        try:
            stored = (await memory.client.get_block("persona")).strip()
            if stored:
                persona_text = stored
        except Exception:  # noqa: BLE001
            logger.exception("failed to load persona for Daily; using default")

    llm = OpenAILLMService(
        api_key=api_key,
        base_url=base_url,
        settings=OpenAILLMService.Settings(
            model=model,
            system_instruction=persona_text,
        ),
    )
    tts = LocalTTSService(
        base_url=settings.vllm_tts_url,
        model=settings.tts_model,
        voice=settings.tts_voice,
        sample_rate=settings.tts_sample_rate,
        response_format=settings.tts_response_format,
        timeout_s=settings.tts_timeout_s,
    )

    context = LLMContext()
    await seed_daily_memory(
        memory=memory,
        session_id=sid,
        add_message=context.add_message,
        skills=skills,
    )

    # Silero VAD + default UserTurnStrategies (stop uses LocalSmartTurnAnalyzerV3).
    # Optional R3 LLMContextSummarizer — Daily path only, off by default.
    assistant_params = build_assistant_aggregator_params(
        enabled=getattr(settings, "daily_context_summary_enabled", False),
        max_context_tokens=getattr(settings, "daily_context_max_tokens", 8000),
        max_unsummarized_messages=None,
        target_context_tokens=getattr(settings, "daily_context_target_tokens", 4000),
        min_messages_after_summary=getattr(
            settings, "daily_context_recent_messages", 4
        ),
    )
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            user_turn_strategies=UserTurnStrategies(),
        ),
        assistant_params=(
            LLMAssistantAggregatorParams(
                enable_auto_context_summarization=assistant_params is not None
                and assistant_params.enable_auto_context_summarization,
                auto_context_summarization_config=(
                    assistant_params.auto_context_summarization_config
                    if assistant_params is not None
                    else None
                ),
            )
            if assistant_params is not None
            else LLMAssistantAggregatorParams()
        ),
    )

    mem_proc = build_memory_turn_processor(
        memory, sid, chat_history_store=chat_history_store,
    )
    skills_proc = build_skills_turn_processor(skills, sid, context)  # type: ignore[arg-type]
    # Skills rematch after STT / before user aggregator so context is updated
    # before the LLM turn. Memory processor stays after LLM for persist.
    stages: list = [
        transport.input(),
        stt,
    ]
    if skills_proc is not None:
        stages.append(skills_proc)
    stages.extend(
        [
            user_agg,
            llm,
        ]
    )
    if mem_proc is not None:
        stages.append(mem_proc)
    stages.extend(
        [
            tts,
            transport.output(),
            assistant_agg,
        ]
    )

    pipeline = Pipeline(stages)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    async def interrupt_pipeline() -> None:
        await task.queue_frame(InterruptionFrame())

    if on_ready is not None:
        on_ready(interrupt_pipeline)

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
