"""Strip thinking / markdown so TTS does not read markup aloud."""

from __future__ import annotations

import re

_THINK_TAG = re.compile(
    r"<think(?:ing)?\b[^>]*>[\s\S]*?</think(?:ing)?>",
    re.IGNORECASE,
)
_THINK_FENCE = re.compile(
    r"```(?:thinking|reasoning|thought)\s*\n[\s\S]*?```",
    re.IGNORECASE,
)
_CODE_FENCE = re.compile(r"```[\w+-]*\n?([\s\S]*?)```")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^>\s?", re.MULTILINE)
_HR = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_BOLD = re.compile(r"\*\*\*([^*]+)\*\*\*|\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC = re.compile(r"\*([^*\n]+)\*|_([^_\n]+)_")
_STRIKE = re.compile(r"~~([^~]+)~~")
_LIST = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUM_LIST = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_MD_NOISE = re.compile(r"[*_~`#]")


def to_speakable_text(text: str) -> str:
    if not text:
        return ""
    s = _THINK_TAG.sub("", text)
    s = _THINK_FENCE.sub("", s)
    s = _CODE_FENCE.sub(r"\1", s)
    s = _INLINE_CODE.sub(r"\1", s)
    s = _IMAGE.sub(r"\1", s)
    s = _LINK.sub(r"\1", s)
    s = _HEADING.sub("", s)
    s = _BLOCKQUOTE.sub("", s)
    s = _HR.sub("", s)
    s = _BOLD.sub(
        lambda m: next(g for g in m.groups() if g is not None),
        s,
    )
    s = _ITALIC.sub(
        lambda m: next(g for g in m.groups() if g is not None),
        s,
    )
    s = _STRIKE.sub(r"\1", s)
    s = _LIST.sub("", s)
    s = _NUM_LIST.sub("", s)
    s = s.replace("|", " ")
    s = _MD_NOISE.sub("", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def clip_for_local_tts(text: str, max_chars: int = 240) -> str:
    """Keep local TTS latency usable — long replies are truncated at a sentence."""
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    window = s[: max_chars + 1]
    for sep in ("。", "！", "？", "；", "\n", ". ", "! ", "? "):
        idx = window.rfind(sep)
        if idx >= max_chars // 3:
            return window[: idx + len(sep)].strip()
    return window[:max_chars].rstrip() + "…"

