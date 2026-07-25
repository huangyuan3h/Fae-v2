"""Inbound channel → same agent core as /api/chat /ws/chat."""

from __future__ import annotations

import logging
from typing import Any

from fae.agent.llm_turn import apply_lazy_skill_tool
from fae.agent.prepare import prepare_chat_request
from fae.agent.skills_runtime import SkillRuntime
from fae.chat_history import ChatHistoryStore
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


class MissingServerLLMError(Exception):
    """Neither client nor server provided a usable LLM API key."""

    def __init__(self, message: str = NO_LLM_REPLY) -> None:
        super().__init__(message)
        self.message = message


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


def merge_llm_config(config: LLMConfig, settings: Settings) -> LLMConfig:
    """Client non-empty fields win; otherwise fill from server env.

    Raises MissingServerLLMError when no API key is available after merge.
    """
    server = resolve_server_llm_config(settings)
    api_key = (config.api_key or "").strip()
    base_url = (config.base_url or "").strip()
    model = (config.model or "").strip()

    if not api_key:
        if server is None:
            raise MissingServerLLMError()
        api_key = server.api_key
    if not base_url:
        base_url = (
            server.base_url
            if server is not None
            else "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    if not model:
        model = server.model if server is not None else "qwen3-max"

    return config.model_copy(
        update={"api_key": api_key, "base_url": base_url, "model": model}
    )


def merge_chat_request(request: ChatRequest, settings: Settings) -> ChatRequest:
    """Return a ChatRequest whose config has an effective API key."""
    merged = merge_llm_config(request.config, settings)
    return request.model_copy(update={"config": merged})


async def handle_inbound_text(
    text: str,
    *,
    settings: Settings,
    llm: LLMClient,
    memory: LettaMemoryService | None = None,
    skills: SkillRuntime | None = None,
    schedule_store: ScheduleStore | None = None,
    activity: ActivityTracker | None = None,
    chat_history_store: ChatHistoryStore | None = None,
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
        from fae.agent.llm_turn import activation_wants_subagent

        subagent_on = bool(
            getattr(settings, "subagent_enabled", True)
        ) and activation_wants_subagent(activation, skills)
        coding_root = str(getattr(settings, "coding_workspace_root", "") or "").strip()
        filesystem_on = bool(coding_root and getattr(settings, "coding_filesystem_enabled", False))
        bash_on = bool(coding_root and getattr(settings, "coding_bash_enabled", False))
        git_on = bool(coding_root and getattr(settings, "coding_git_enabled", False))
        tools_needed = bool(
            (isinstance(skills, SkillRuntime) and activation.tools)
            or sched
            or weather_on
            or subagent_on
            or filesystem_on
            or bash_on
            or git_on
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
                memory=memory,
                subagent_enabled=subagent_on,
                subagent_timeout_s=float(
                    getattr(settings, "subagent_timeout_s", 60.0) or 60.0
                ),
                workspace_root=coding_root,
                filesystem_enabled=filesystem_on,
                bash_enabled=bash_on,
                bash_timeout_s=float(getattr(settings, "coding_bash_timeout_s", 30.0)),
                git_enabled=git_on,
                git_timeout_s=float(getattr(settings, "coding_git_timeout_s", 20.0)),
            )
            if early and "日程工具" in early and callable(on_schedule_mutated):
                on_schedule_mutated()

        if early is not None:
            reply = early
        else:
            response = await llm.chat(prepared)
            reply = response.content or ""

        if (
            chat_history_store is not None
            and not chat_history_store.closed
            and user_text
        ):
            try:
                chat_history_store.append(
                    sid, user_text, reply,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Channel chat history persist failed")

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
