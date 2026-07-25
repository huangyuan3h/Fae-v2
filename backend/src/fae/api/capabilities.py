"""GET /api/capabilities — discover channels, modes, tools (P7)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from fae.agent.known_tools import known_tool_names
from fae.channels.bridge import resolve_server_llm_config
from fae.channels.telegram import telegram_ready
from fae.api.auth import client_token_required
from fae.config import Settings
from fae.scheduler.loop import ProactiveLoop

router = APIRouter(tags=["capabilities"])


def build_capabilities(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    tg_task = getattr(request.app.state, "telegram_task", None)
    telegram_running = bool(tg_task is not None and not tg_task.done())
    proactive = getattr(request.app.state, "proactive", None)
    scheduler_running = bool(
        isinstance(proactive, ProactiveLoop) and proactive._started
    )
    server_llm = resolve_server_llm_config(settings) is not None

    return {
        "app": settings.app_name,
        "channels": {
            "web_ws": True,
            "http_chat": True,
            "telegram": {
                "configured": telegram_ready(settings),
                "running": telegram_running,
            },
        },
        "modes": {
            "text": True,
            "voice_daily": bool((settings.daily_api_key or "").strip()),
            "tts_local": bool((settings.vllm_tts_url or "").strip()),
        },
        "tools": sorted(known_tool_names()),
        "tool_runtime": {
            "workspace_configured": bool((settings.coding_workspace_root or "").strip()),
            "filesystem_enabled": bool(settings.coding_filesystem_enabled),
            "bash_enabled": bool(settings.coding_bash_enabled),
            "git_enabled": bool(settings.coding_git_enabled),
        },
        "skills_enabled": bool(settings.skills_enabled),
        "subagent_enabled": bool(settings.subagent_enabled),
        "scheduler_enabled": bool(settings.scheduler_enabled),
        "scheduler_running": scheduler_running,
        "llm": {
            "server_configured": server_llm,
        },
        "auth": {
            "client_token_required": client_token_required(settings),
        },
        "status": {
            "scheduler": (
                "ok"
                if scheduler_running
                else ("off" if not settings.scheduler_enabled else "down")
            ),
            "telegram": (
                "ok"
                if telegram_running
                else (
                    "off"
                    if not getattr(settings, "telegram_enabled", True)
                    else (
                        "misconfigured"
                        if not telegram_ready(settings)
                        else "down"
                    )
                )
            ),
            "proactive_llm": "ok" if server_llm else "misconfigured",
        },
    }


@router.get("/api/capabilities")
async def capabilities(request: Request) -> dict[str, Any]:
    """Capability discovery for thin clients (no secrets)."""
    return build_capabilities(request)
