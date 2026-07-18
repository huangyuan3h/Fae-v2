"""Heuristic fact extraction for Phase 2.1 persist_turn (M2-1)."""

from __future__ import annotations

import re

from fae.memory.schemas import FactIn, UserProfile

# "我叫小明" / "我的名字是小明" / "My name is Ming"
_NAME_PATTERNS = (
    re.compile(r"(?:我叫|我的名字是|我是)\s*([^\s，。,.!！？?]{1,32})"),
    re.compile(r"(?i)(?:my name is|i am|i'm)\s+([A-Za-z][\w\- ]{0,31})"),
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


def facts_from_turn(
    *,
    user_text: str,
    assistant_text: str = "",
    session_id: str | None = None,
) -> tuple[UserProfile | None, list[FactIn]]:
    """Return profile update + facts to persist from one user turn."""
    _ = assistant_text
    profile: UserProfile | None = None
    facts: list[FactIn] = []
    name = extract_display_name(user_text)
    if name:
        profile = UserProfile(display_name=name)
        facts.append(
            FactIn(
                content=f"User's name is {name}",
                tags=["identity", "name"],
                session_id=session_id,
            )
        )
    return profile, facts
