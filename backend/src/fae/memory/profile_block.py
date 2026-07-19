"""Core-memory ``human`` block: unstructured important user notes.

The human block is plain-language durable identity (name, home city, prefs).
Optional ``Key: value`` lines are still recognized when present, but the
primary store is freeform prose that conversation can create and correct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from fae.memory.defaults import DEFAULT_HUMAN

_DEFAULT_HUMAN = DEFAULT_HUMAN

# Optional structured keys (still supported for tooling / migration).
CITY_KEY = "City"
TIMEZONE_KEY = "Timezone"
NAME_KEY = "Name"
DIETARY_KEY = "Avoids"

_KEY_LINE = re.compile(r"^([A-Za-z][\w ]{0,40}):\s*(.+)$")

# Freeform location lines we write / replace.
_LOCATION_LINE = re.compile(
    r"(?i)^(?:lives?\s+in|home(?:\s+city)?|located\s+in|住在|家在)[:\s]+(.+?)\.?$"
)
_NAME_LINE_FREE = re.compile(
    r"(?i)^(?:name|called|叫|名字)[:\s]+(.+?)\.?$"
)
_TZ_LINE_FREE = re.compile(
    r"(?i)^(?:timezone|time\s*zone|时区)[:\s]+([A-Za-z][\w/\-+]{2,40})\.?$"
)

# Inline mentions inside longer notes
_INLINE_LIVES = re.compile(
    r"(?i)(?:lives?\s+in|home\s+city\s+is|located\s+in|住在|家在)\s+"
    r"([^\s，。,.!！？?;；]{1,32})"
)


@dataclass
class ParsedHumanProfile:
    display_name: str | None = None
    city: str | None = None
    timezone: str | None = None
    preferences: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    raw: str = ""


def default_human_text() -> str:
    return _DEFAULT_HUMAN


def parse_human_profile(text: str) -> ParsedHumanProfile:
    """Parse structured keys and freeform location/name/timezone lines."""
    raw = text or ""
    out = ParsedHumanProfile(raw=raw)
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _KEY_LINE.match(stripped)
        if m:
            key, value = m.group(1).strip(), m.group(2).strip()
            if not value:
                continue
            key_norm = key.lower()
            if key_norm == "name":
                out.display_name = value
            elif key_norm == "city":
                out.city = value
                out.preferences[CITY_KEY] = value
            elif key_norm in {"timezone", "tz", "time zone"}:
                out.timezone = value
                out.preferences[TIMEZONE_KEY] = value
            else:
                out.preferences[key] = value
            continue

        loc = _LOCATION_LINE.match(stripped)
        if loc and not out.city:
            out.city = loc.group(1).strip(" \"'.")
            continue
        nm = _NAME_LINE_FREE.match(stripped)
        if nm and not out.display_name:
            out.display_name = nm.group(1).strip(" \"'.")
            continue
        tz = _TZ_LINE_FREE.match(stripped)
        if tz and not out.timezone:
            out.timezone = tz.group(1).strip()
            continue
        out.notes.append(stripped)

    if not out.city:
        for note in out.notes:
            inline = _INLINE_LIVES.search(note)
            if inline:
                out.city = inline.group(1).strip(" \"'.")
                break
    return out


def _is_location_line(line: str) -> bool:
    s = line.strip()
    if _LOCATION_LINE.match(s):
        return True
    if s.lower().startswith("city:"):
        return True
    return False


def _is_name_line(line: str) -> bool:
    s = line.strip()
    if s.lower().startswith("name:"):
        return True
    return bool(_NAME_LINE_FREE.match(s))


def _is_timezone_line(line: str) -> bool:
    s = line.strip()
    if s.lower().startswith("timezone:") or s.lower().startswith("tz:"):
        return True
    return bool(_TZ_LINE_FREE.match(s))


_DIETARY_LINE = re.compile(
    r"(?i)^(?:avoids?|dietary|忌口|不吃|过敏)[:\s]+(.+?)\.?$"
)


def _is_dietary_line(line: str) -> bool:
    s = line.strip()
    return bool(_DIETARY_LINE.match(s)) or s.lower().startswith("avoids:")


def upsert_location_note(existing: str, city: str) -> str:
    """Write/replace a freeform 'Lives in {city}.' note in the human block."""
    city = (city or "").strip()
    if not city:
        return (existing or "").strip() or _DEFAULT_HUMAN
    lines = [ln for ln in (existing or "").splitlines() if ln.strip()]
    # Drop placeholder default when learning the first real fact.
    if len(lines) == 1 and "Unknown user" in lines[0]:
        lines = []
    kept = [ln for ln in lines if not _is_location_line(ln)]
    kept.append(f"Lives in {city}.")
    return "\n".join(kept).strip() or _DEFAULT_HUMAN


def upsert_name_note(existing: str, name: str) -> str:
    name = (name or "").strip()
    if not name:
        return (existing or "").strip() or _DEFAULT_HUMAN
    lines = [ln for ln in (existing or "").splitlines() if ln.strip()]
    if len(lines) == 1 and "Unknown user" in lines[0]:
        lines = []
    kept = [ln for ln in lines if not _is_name_line(ln)]
    kept.insert(0, f"Name: {name}")
    return "\n".join(kept).strip() or _DEFAULT_HUMAN


def upsert_timezone_note(existing: str, timezone: str) -> str:
    timezone = (timezone or "").strip()
    if not timezone:
        return (existing or "").strip() or _DEFAULT_HUMAN
    lines = [ln for ln in (existing or "").splitlines() if ln.strip()]
    if len(lines) == 1 and "Unknown user" in lines[0]:
        lines = []
    kept = [ln for ln in lines if not _is_timezone_line(ln)]
    kept.append(f"Timezone: {timezone}")
    return "\n".join(kept).strip() or _DEFAULT_HUMAN


def upsert_dietary_note(existing: str, avoid: str) -> str:
    """Write/replace a freeform 'Avoids: …' dietary note."""
    avoid = (avoid or "").strip().rstrip("。.!！?")
    if not avoid:
        return (existing or "").strip() or _DEFAULT_HUMAN
    lines = [ln for ln in (existing or "").splitlines() if ln.strip()]
    if len(lines) == 1 and "Unknown user" in lines[0]:
        lines = []
    kept = [ln for ln in lines if not _is_dietary_line(ln)]
    kept.append(f"Avoids: {avoid}.")
    return "\n".join(kept).strip() or _DEFAULT_HUMAN


def merge_human_profile(
    existing: str,
    *,
    display_name: str | None = None,
    preferences: dict[str, str] | None = None,
    notes: str | None = None,
) -> str:
    """Merge profile fields into the human block without clobbering other lines."""
    text = existing or ""
    prefs = dict(preferences or {})

    # Normalize city/timezone keys into freeform upserts.
    city = prefs.pop(CITY_KEY, None) or prefs.pop("city", None) or prefs.pop("City", None)
    timezone = (
        prefs.pop(TIMEZONE_KEY, None)
        or prefs.pop("timezone", None)
        or prefs.pop("Timezone", None)
        or prefs.pop("tz", None)
    )
    dietary = (
        prefs.pop(DIETARY_KEY, None)
        or prefs.pop("dietary", None)
        or prefs.pop("Avoid", None)
        or prefs.pop("avoid", None)
    )
    if display_name:
        text = upsert_name_note(text, display_name)
    if city:
        text = upsert_location_note(text, city)
    if timezone:
        text = upsert_timezone_note(text, timezone)
    if dietary:
        text = upsert_dietary_note(text, dietary)

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines and not prefs and not notes:
        return _DEFAULT_HUMAN

    def _upsert_key(prefix: str, value: str) -> None:
        nonlocal lines
        rebuilt: list[str] = []
        found = False
        for line in lines:
            if line.lower().startswith(prefix.lower() + ":"):
                if not found:
                    rebuilt.append(f"{prefix}: {value}")
                    found = True
            else:
                rebuilt.append(line)
        if not found:
            rebuilt.append(f"{prefix}: {value}")
        lines = rebuilt

    for key, value in prefs.items():
        val = (value or "").strip()
        if val:
            _upsert_key(key, val)
    if notes and notes.strip():
        note = notes.strip()
        if note not in lines:
            lines.append(note)

    return "\n".join(lines).strip() or _DEFAULT_HUMAN
