"""Heuristic fact extraction for persist_turn — name, location, corrections."""

from __future__ import annotations

import re

from fae.memory.profile_block import CITY_KEY, TIMEZONE_KEY
from fae.memory.schemas import FactIn, UserProfile

# "我叫小明" / "我的名字是小明" / "My name is Ming"
_NAME_PATTERNS = (
    re.compile(r"(?:我叫|我的名字是)\s*([^\s，。,.!！？?]{1,32})"),
    re.compile(r"(?i)(?:my name is)\s+([A-Za-z][\w\- ]{0,31})"),
)

# Explicit home-city statements (avoid bare "我是/我在" — too noisy)
_CITY_PATTERNS = (
    re.compile(
        r"(?:我住在|我家在|我的城市是|我位于|现在住在|我搬到了?)\s*"
        r"([^\s，。,.!！？?]{1,32})"
    ),
    re.compile(
        r"(?i)(?:i live in|i moved to|my (?:home )?city is|based in|now in)\s+"
        r"([A-Za-z][\w\- ]{0,31})"
    ),
)

# Corrections: "不对，是上海" / "不是北京是杭州" / "改成上海" / "actually Shanghai"
_CITY_CORRECTION_PATTERNS = (
    re.compile(r"不是.+?是\s*([^\s，。,.!！？?]{1,32})"),
    re.compile(
        r"(?:不对|错了)[，,]?\s*(?:是\s*)?([^\s，。,.!！？?]{1,32})"
    ),
    re.compile(r"(?:改成|换成|其实是|应该是)\s*([^\s，。,.!！？?]{1,32})"),
    re.compile(
        r"(?i)(?:actually|correction|i meant)\s+"
        r"([A-Za-z][\w\- ]{0,31})"
    ),
)

_TZ_PATTERNS = (
    re.compile(r"(?:时区(?:是|为)|timezone(?:\s+is)?)\s*([A-Za-z][\w/\-+]{2,40})"),
)

# Assistant just asked for location → accept a short city-only reply
_ASSISTANT_ASKED_LOCATION = re.compile(
    r"(?i)(?:哪[个座]?城市|哪个城市|在哪[里儿]?|住在哪|什么地方|"
    r"which city|where (?:do you )?live|what city|your (?:home )?city|location)"
)

_CITY_STOPWORDS = {
    "想",
    "家",
    "这",
    "那",
    "这里",
    "那里",
    "的",
    "了",
    "啊",
    "吧",
    "a",
    "an",
    "the",
    "hurry",
    "trouble",
    "here",
    "there",
}


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


def _clean_city(raw: str | None) -> str | None:
    if not raw:
        return None
    city = raw.strip(" \"'。.!！?")
    if not city or len(city) < 2:
        return None
    if city.lower() in _CITY_STOPWORDS:
        return None
    # Reject obvious non-city short answers
    if len(city) > 32:
        return None
    return city


def extract_city(user_text: str, *, assistant_text: str = "") -> str | None:
    text = (user_text or "").strip()
    if not text:
        return None

    for pattern in _CITY_CORRECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            city = _clean_city(match.group(1))
            if city:
                return city

    for pattern in _CITY_PATTERNS:
        match = pattern.search(text)
        if match:
            city = _clean_city(match.group(1))
            if city:
                return city

    # After FAE asked for city: accept "北京" / "Shanghai"
    if assistant_text and _ASSISTANT_ASKED_LOCATION.search(assistant_text):
        # Single token / short phrase without question marks
        if "?" not in text and "？" not in text and len(text) <= 32:
            # Prefer whole text if it looks like a place name
            if re.fullmatch(r"[\w\u4e00-\u9fff\- ]{2,32}", text):
                city = _clean_city(text)
                if city:
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
    prefs: dict[str, str] = {}
    facts: list[FactIn] = []
    name = extract_display_name(user_text)
    city = extract_city(user_text, assistant_text=assistant_text)
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
