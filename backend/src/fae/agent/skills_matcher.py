"""Match user text to trigger-based skills (keywords + Jaccard)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from fae.agent.skills_schema import LoadStrategy, Skill

_TOKEN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

# Strong signals for technical_debugging even if frontmatter is edited lightly.
_STACK_HINTS = (
    "traceback",
    "stack trace",
    "stacktrace",
    "exception",
    "typeerror",
    "valueerror",
    "nullpointer",
    "segfault",
    "报错",
    "异常",
    "堆栈",
)


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "") if len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


@dataclass(frozen=True)
class MatchScore:
    name: str
    score: float


def score_skill(user_text: str, skill: Skill) -> float:
    """Return 0..1 relevance score for a trigger_based skill."""
    text = (user_text or "").strip()
    if not text:
        return 0.0
    lower = text.lower()
    best = 0.0

    # Built-in boost for debugging skill
    if skill.meta.name == "technical_debugging":
        for hint in _STACK_HINTS:
            if hint in lower:
                best = max(best, 0.95)
        if "traceback (most recent call last)" in lower:
            best = max(best, 1.0)
        if re.search(r"error[:\s]", lower) and (
            "line " in lower or "file " in lower or ".py" in lower
        ):
            best = max(best, 0.9)

    user_tokens = _tokenize(text)
    for trigger in skill.meta.triggers:
        t = (trigger or "").strip()
        if not t:
            continue
        tl = t.lower()
        if tl in lower:
            best = max(best, 0.85)
            continue
        # All significant words from trigger present
        trig_tokens = _tokenize(t)
        if trig_tokens and trig_tokens <= user_tokens:
            best = max(best, 0.75)
        else:
            best = max(best, _jaccard(user_tokens, trig_tokens) * 0.7)
    return best


def match_trigger_skills(
    user_text: str,
    skills: list[Skill],
    *,
    threshold: float = 0.35,
) -> list[MatchScore]:
    """Score enabled trigger_based skills above threshold, highest first."""
    out: list[MatchScore] = []
    for skill in skills:
        if skill.meta.load_strategy != LoadStrategy.TRIGGER_BASED:
            continue
        if not skill.meta.enabled:
            continue
        s = score_skill(user_text, skill)
        if s >= threshold:
            out.append(MatchScore(name=skill.meta.name, score=s))
    out.sort(key=lambda m: (-m.score, m.name))
    return out
