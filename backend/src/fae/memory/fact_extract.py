"""Heuristic fact extraction for Phase 2.1 persist_turn (M2-1)."""

from __future__ import annotations

import re

from fae.memory.profile_block import CITY_KEY, TIMEZONE_KEY
from fae.memory.schemas import FactIn, UserProfile

# "我叫小明" / "我的名字是小明" / "My name is Ming"
_NAME_PATTERNS = (
    re.compile(r"(?:我叫|我的名字是|我是)\s*([^\s，。,.!！？?]{1,32})"),
    re.compile(r"(?i)(?:my name is|i am|i'm)\s+([A-Za-z][\w\- ]{0,31})"),
)

# "我住在北京" / "我家在上海" / "I live in Tokyo"
_CITY_PATTERNS = (
    re.compile(
        r"(?:我住在|我在|我家在|我的城市是|我位于)\s*"
        r"([^\s，。,.!！？?]{1,32})"
    ),
    re.compile(
        r"(?i)(?:i live in|i'm in|i am in|my city is|based in)\s+"
        r"([A-Za-z][\w\- ]{0,31})"
    ),
)

# "时区是 Asia/Shanghai" / "timezone is America/New_York"
_TZ_PATTERNS = (
    re.compile(r"(?:时区(?:是|为)|timezone(?:\s+is)?)\s*([A-Za-z][\w/\-+]{2,40})"),
)


def extract_display_name(user_text: str) -> str | None:
    text = (user_text or "").strip()
    if not text:
        return None
    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            name = match.group(1).strip(" \"'")
            if name and name.lower() not in {"a", "an", "the", "叫", "是"}:
                return name
    return None


def extract_city(user_text: str) -> str | None:
    text = (user_text or "").strip()
    if not text:
        return None
    for pattern in _CITY_PATTERNS:
        match = pattern.search(text)
        if match:
            city = match.group(1).strip(" \"'")
            # Avoid false positives like "我在想" / "I'm in a hurry"
            if not city or len(city) < 2:
                continue
            lower = city.lower()
            if lower in {
                "想",
                "家",
                "这",
                "那",
                "这里",
                "那里",
                "a",
                "an",
                "the",
                "hurry",
                "trouble",
            }:
                continue
            return city
    return None


def extract_timezone(user_text: str) -> str | None:
    text = (user_text or "").strip()
    if not text:
        return None
    for pattern in _TZ_PATTERNS:
        match = pattern.search(text)
        if match:
            tz = match.group(1).strip(" \"'")
            if tz and "/" in tz:
                return tz
    return None


def facts_from_turn(
    *,
    user_text: str,
    assistant_text: str = "",
    session_id: str | None = None,
) -> tuple[UserProfile | None, list[FactIn]]:
    """Return profile update + facts to persist from one user turn."""
    _ = assistant_text
    prefs: dict[str, str] = {}
    facts: list[FactIn] = []
    name = extract_display_name(user_text)
    city = extract_city(user_text)
    timezone = extract_timezone(user_text)

    if name:
        facts.append(
            FactIn(
                content=f"User's name is {name}",
                tags=["identity", "name"],
                session_id=session_id,
            )
        )
    if city:
        prefs[CITY_KEY] = city
        facts.append(
            FactIn(
                content=f"User lives in {city}",
                tags=["identity", "location", "city"],
                session_id=session_id,
            )
        )
    if timezone:
        prefs[TIMEZONE_KEY] = timezone
        facts.append(
            FactIn(
                content=f"User timezone is {timezone}",
                tags=["identity", "timezone"],
                session_id=session_id,
            )
        )

    profile: UserProfile | None = None
    if name or prefs:
        profile = UserProfile(
            display_name=name,
            preferences=prefs,
        )
    return profile, facts
