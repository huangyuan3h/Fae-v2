"""Strip thinking / markdown / emoji so TTS does not read markup or noise aloud.

Single helper `to_speakable_text` for both the browser path (TTS queue) and the
Daily / Pipecat bot. Belt-and-suspenders against common LLM misbehavior in
voice replies (guffawing emoji, English laugh fillers, singsong cadence driven
by chains of `~` / `!` / `…`, ZWSJ-spaced emoji that survive a single normalise
pass, etc.).
"""

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
_CODE_FENCE = re.compile(r"```[\w+-]*\n?[\s\S]*?```")
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
# One or more consecutive GFM pipe-table lines
_PIPE_TABLE = re.compile(r"(?:^|\n)(?:\|[^\n]*\|(?:\n|$))+")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)

# --- Voice hygiene: emoji, kaomoji, fillers, invisible noise -----------------

# Combined Unicode-range cover for emoji + extended pictographic symbols. Mirrors
# the same UAX #51 ranges that `emoji-regex` (JS) ships with, so the backend and
# UI stripper stay in lock-step. Source-of-truth: Unicode TR51 + emoji-data.
_EMOJI_RANGES = (
    "\U0001F1E0-\U0001F1FF"  # flags (regional indicators)
    "\U0001F300-\U0001F5FF"  # misc symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"  # alchemical
    "\U0001F780-\U0001F7FF"  # geometric extended
    "\U0001F800-\U0001F8FF"  # arrows supplemental
    "\U0001F900-\U0001F9FF"  # supplemental symbols & pictographs
    "\U0001FA00-\U0001FA6F"  # chess / symbols & pictographs ext-A
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs ext-A continued
    "\U0001FB00-\U0001FBFF"  # symbols for legacy computing
    "\u2600-\u26FF"          # misc symbols
    "\u2700-\u27BF"          # dingbats
    "\u2300-\u23FF"          # misc technical (clock faces etc.)
    "\u2B00-\u2BFF"          # misc symbols & arrows
    "\u2900-\u297F"          # supplemental arrows B
    # Variation selectors (FE0F / FE0E) ride along with their base.
    "\uFE00-\uFE0F"
    # Skin-tone modifiers and other combining emoji pieces.
    "\U0001F3FB-\U0001F3FF"
)
_EMOJI_RUN = re.compile(
    f"[\u200d{_EMOJI_RANGES}]+(?:\u200d[\u200d{_EMOJI_RANGES}]+)*",
    re.UNICODE,
)

# Zero-width / bidi / deprecated formatting characters that survive naive strip
# and end up as audible artifacts on some TTS stacks. Replace with a regular space
# so we don't accidentally glue words together.
_INVISIBLE = re.compile(
    "[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF"
    "\U000E0020-\U000E007F"
    "\u00AD]"
)
# ASCII kaomoji that models occasionally emit. Kept narrow on purpose — we only
# catch the common Western faces; CJK kaomoji like (╯°□°)╯ are caught by emoji range.
_ASCII_KAOMOJI = re.compile(
    r"(?:"
    # Western-style: :) ;( =D :P /w\ ^_^ etc.
    r"[:;=8][\-o*']?[\)\]\(\[dDpP/\\{}|><*^@_~]+"
    r"|"
    # Parenthesised CJK-flavored: (^_^) (*^▽^*) (T_T) (T^T)
    r"[\(\[]+[\-_o*^~]?[_\-^～~\.\\]*[\\^▽°´☆\*][\-_o*^~]?[\)\]]+"
    r"|"
    # Bareface emoticons with trailing / leading face bits
    r"[\)\]\(\[dDpP/\\{}|><*^@]+[\-o*']?[:;=]"
    r")"
)
# English laugh / filler tokens — drop the leading word and any trailing `~`.
# Anchored on word boundaries so we don't mangle words like "lolcat".
_FILLERS = re.compile(
    r"\b(?:"
    r"lmao+|lol+|rofl+|haha+|hehe+|hihi+|x[dD]|"
    r"omg|wtf|btw|idk|smh|fml|yolo|nvm|imo|imho|tbh"
    r")+\b[~～]?",
    re.IGNORECASE,
)
# Excessive trailing / leading punctuation that feeds singsong cadence: "!!", "??",
# "……", "~~~", "！！！". Keep one.
_PUNCT_RUN = re.compile(r"([。！？!?~～.,，、；：])\1{1,}")
# Lone ~ / ~ suffix mostly from model emoting; drop to nothing but preserve
# sentence cadence around words.
_WAVY = re.compile(r"\s*[~～]+\s*")


def _drop_emoji(text: str) -> str:
    """Replace emoji runs with a space; trims the orphan space in `_collapse`."""
    return _EMOJI_RUN.sub(" ", text)


def _normalize_punct(text: str) -> str:
    text = _PUNCT_RUN.sub(r"\1", text)
    # Strip full-width space + zero-width joiners that sneak into replies.
    text = text.replace("　", " ").replace("‍", "")
    return text


def _collapse(text: str) -> str:
    """Trim duplicate whitespace created by replacements and tidy line breaks."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def to_speakable_text(text: str) -> str:
    if not text:
        return ""
    s = _THINK_TAG.sub("", text)
    s = _THINK_FENCE.sub("", s)
    # Repair collapsed table rows before stripping
    s = s.replace("||", "|\n|")
    # Drop code fences and tables entirely — do not read aloud
    s = _CODE_FENCE.sub("\n", s)
    s = _PIPE_TABLE.sub("\n", s)
    s = _TABLE_LINE.sub("", s)
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

    # Voice hygiene — applied after markdown cleanup so emoji hidden inside
    # fenced code blocks / table cells still get caught.
    s = _drop_emoji(s)
    s = _INVISIBLE.sub(" ", s)
    s = _ASCII_KAOMOJI.sub(" ", s)
    s = _FILLERS.sub(" ", s)
    s = _WAVY.sub(" ", s)
    s = _normalize_punct(s)
    s = _collapse(s)
    return s


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
