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

# Short / ambiguous triggers need supporting context (Phase Q.2).
_SHORT_TRIGGER_MAX_LEN = 3
_SHORT_EN_WORDS = frozenset(
    {
        "bug",
        "draft",
        "fix",
        "error",
        "crash",
        "help",
        "plan",
        "trip",
        "write",
    }
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


def _is_short_trigger(trigger: str) -> bool:
    t = (trigger or "").strip()
    if not t:
        return True
    if len(t) <= _SHORT_TRIGGER_MAX_LEN:
        return True
    # Single ASCII word like "bug" / "draft"
    if re.fullmatch(r"[A-Za-z]+", t) and t.lower() in _SHORT_EN_WORDS:
        return True
    if re.fullmatch(r"[A-Za-z]+", t) and len(t) <= 5:
        return True
    return False


def _has_extra_substance(text: str, trigger: str) -> bool:
    """User text is longer than the short trigger alone (Chinese-safe)."""
    t = (text or "").strip()
    trig = (trigger or "").strip()
    if not t or not trig:
        return False
    # Continuous CJK often tokenizes as one blob — use char length.
    return len(t) >= len(trig) + 2


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
                # Lone short Chinese "报错"/"异常" is weak; richer phrases stay strong.
                if hint in ("报错", "异常") and not _has_extra_substance(text, hint):
                    best = max(best, 0.30)
                else:
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
        short = _is_short_trigger(t)
        if tl in lower:
            if short:
                # Alone short hits stay below threshold (0.35); longer utterances OK.
                if _has_extra_substance(text, t):
                    best = max(best, 0.75)
                else:
                    best = max(best, 0.30)
            else:
                best = max(best, 0.85)
            continue
        # All significant words from trigger present
        trig_tokens = _tokenize(t)
        if trig_tokens and trig_tokens <= user_tokens:
            if short and not _has_extra_substance(text, t):
                best = max(best, 0.30)
            else:
                best = max(best, 0.75)
        else:
            j = _jaccard(user_tokens, trig_tokens) * 0.7
            if short and not _has_extra_substance(text, t):
                j = min(j, 0.30)
            best = max(best, j)
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
