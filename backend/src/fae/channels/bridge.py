"""Inbound channel → same agent core as /api/chat /ws/chat."""

from __future__ import annotations

import logging
from typing import Any

from fae.agent.llm_turn import apply_lazy_skill_tool
from fae.agent.prepare import prepare_chat_request
from fae.agent.skills_runtime import SkillRuntime
from fae.config import Settings
from fae.llm import ChatMessage, ChatRequest, LLMClient, LLMConfig, LLMError
from fae.pipecat.services.letta_memory import LettaMemoryService
from fae.scheduler import ActivityTracker
from fae.scheduler.store import ScheduleStore
from fae.tools.weather import weather_likely

logger = logging.getLogger("fae.channels.bridge")

DEFAULT_SESSION_ID = "default"
NO_LLM_REPLY = (
    "服务端未配置 LLM（PROACTIVE_LLM_API_KEY 或 DASHSCOPE_API_KEY），无法回复。"
)


def resolve_server_llm_config(settings: Settings) -> LLMConfig | None:
    """Server-side model for channels / proactive (never browser localStorage)."""
    key = (
        (settings.proactive_llm_api_key or "").strip()
        or (settings.dashscope_api_key or "").strip()
    )
    if not key:
        return None
    base = (settings.proactive_llm_base_url or "").strip() or (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    model = (settings.proactive_llm_model or "").strip() or "qwen3-max"
    return LLMConfig(api_key=key, base_url=base, model=model)


async def handle_inbound_text(
    text: str,
    *,
    settings: Settings,
    llm: LLMClient,
    memory: LettaMemoryService | None = None,
    skills: SkillRuntime | None = None,
    schedule_store: ScheduleStore | None = None,
    activity: ActivityTracker | None = None,
    session_id: str = DEFAULT_SESSION_ID,
    on_schedule_mutated: Any | None = None,
) -> str:
    """Run one user turn through prepare → tools/LLM → persist. Returns reply text."""
    user_text = (text or "").strip()
    if not user_text:
        return ""

    cfg = resolve_server_llm_config(settings)
    if cfg is None:
        return NO_LLM_REPLY

    sid = (session_id or "").strip() or DEFAULT_SESSION_ID
    body = ChatRequest(
        config=cfg,
        messages=[ChatMessage(role="user", content=user_text)],
        session_id=sid,
    )

    try:
        prepared, activation, default_city = await prepare_chat_request(
            body,
            session_id=sid,
            memory=memory,
            skills=skills,
            default_city=getattr(settings, "weather_default_city", "") or "",
            default_timezone=getattr(settings, "weather_default_timezone", "")
            or "",
        )

        early: str | None = None
        sched = (
            schedule_store
            if (
                isinstance(schedule_store, ScheduleStore)
                and getattr(settings, "scheduler_enabled", False)
            )
            else None
        )
        weather_on = bool(getattr(settings, "weather_enabled", True)) and (
            weather_likely(user_text) or "weather_briefing" in activation.active
        )
        tools_needed = bool(
            (isinstance(skills, SkillRuntime) and activation.tools)
            or sched
            or weather_on
        )
        if tools_needed:
            prepared, activation, early = await apply_lazy_skill_tool(
                llm,
                prepared,
                activation,
                skills if isinstance(skills, SkillRuntime) else None,
                session_id=sid,
                schedule_store=sched,
                weather_enabled=weather_on,
                default_city=default_city,
            )
            if early and "日程工具" in early and callable(on_schedule_mutated):
                on_schedule_mutated()

        if early is not None:
            reply = early
        else:
            response = await llm.chat(prepared)
            reply = response.content or ""

        if memory is not None and memory.enabled and user_text:
            await memory.persist_turn(
                session_id=sid,
                user_text=user_text,
                assistant_text=reply,
            )
        elif activity is not None:
            activity.touch(sid)

        return reply
    except LLMError as e:
        logger.warning("channel inbound LLM error: %s %s", e.code, e.message)
        return f"回复失败（{e.code}）：{e.message}"
    except Exception:  # noqa: BLE001
        logger.exception("channel inbound failed")
        return "处理消息时出错，请稍后再试。"
