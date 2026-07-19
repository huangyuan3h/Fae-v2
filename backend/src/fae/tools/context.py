"""Inject local time / default city into the chat system prompt."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fae.llm.types import ChatMessage, ChatRequest
from fae.memory.profile_block import parse_human_profile

if TYPE_CHECKING:
    from fae.pipecat.services.letta_memory import LettaMemoryService

_CONTEXT_OPEN = "<fae_context>"
_CONTEXT_CLOSE = "</fae_context>"


async def resolve_location_defaults(
    memory: LettaMemoryService | None,
    *,
    env_city: str = "",
    env_timezone: str = "",
) -> tuple[str | None, str | None]:
    """Resolve (city, timezone) from env overrides then human memory block."""
    city = (env_city or "").strip() or None
    timezone = (env_timezone or "").strip() or None
    if memory is None or not memory.enabled or memory.client is None:
        return city, timezone
    try:
        human = await memory.client.get_block("human")
    except Exception:  # noqa: BLE001
        return city, timezone
    profile = parse_human_profile(human)
    return city or profile.city, timezone or profile.timezone


def _now_in_timezone(tz_name: str | None) -> tuple[datetime, str]:
    """Return (aware datetime, timezone label). Falls back to system local."""
    name = (tz_name or "").strip()
    if name:
        try:
            tz = ZoneInfo(name)
            return datetime.now(tz), name
        except ZoneInfoNotFoundError:
            pass
    local = datetime.now().astimezone()
    label = str(local.tzinfo) if local.tzinfo else "local"
    return local, label


def build_context_block(
    *,
    human_block: str = "",
    city: str | None = None,
    timezone: str | None = None,
) -> str:
    """Build a short runtime context block for the LLM."""
    profile = parse_human_profile(human_block)
    resolved_city = (city or profile.city or "").strip()
    resolved_tz = (timezone or profile.timezone or "").strip() or None
    now, tz_label = _now_in_timezone(resolved_tz)

    lines = [
        "Runtime context (authoritative — use for 'today', 'now', local time):",
        f"- Local datetime: {now.strftime('%Y-%m-%d %H:%M %A')}",
        f"- Timezone: {tz_label}",
    ]
    if resolved_city:
        lines.append(f"- Default city: {resolved_city}")
    else:
        lines.append("- Default city: (unknown — ask the user if needed)")
    lines.append(
        "- For live weather, call get_weather. Do not claim you lack weather access."
    )
    return f"{_CONTEXT_OPEN}\n" + "\n".join(lines) + f"\n{_CONTEXT_CLOSE}"


def inject_context(request: ChatRequest, block: str) -> ChatRequest:
    """Insert context after leading system messages (memory/skills stay first)."""
    text = (block or "").strip()
    if not text:
        return request
    messages = list(request.messages)
    insert_at = 0
    while insert_at < len(messages) and messages[insert_at].role == "system":
        insert_at += 1
    messages.insert(insert_at, ChatMessage(role="system", content=text))
    return request.model_copy(update={"messages": messages})
