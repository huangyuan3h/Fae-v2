"""Parse / merge the core-memory human block (Name, City, Timezone, …)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DEFAULT_HUMAN = "Unknown user. Learn and remember their name and preferences."

# Preference keys stored as "Key: value" lines in the human block.
CITY_KEY = "City"
TIMEZONE_KEY = "Timezone"
NAME_KEY = "Name"

_KEY_LINE = re.compile(r"^([A-Za-z][\w ]{0,40}):\s*(.+)$")


@dataclass
class ParsedHumanProfile:
    display_name: str | None = None
    city: str | None = None
    timezone: str | None = None
    preferences: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    raw: str = ""


def parse_human_profile(text: str) -> ParsedHumanProfile:
    """Parse Name / City / Timezone and other Key: value preferences."""
    raw = text or ""
    out = ParsedHumanProfile(raw=raw)
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _KEY_LINE.match(stripped)
        if not m:
            out.notes.append(stripped)
            continue
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
            # Preserve original capitalization for unknown keys
            out.preferences[key] = value
    return out


def merge_human_profile(
    existing: str,
    *,
    display_name: str | None = None,
    preferences: dict[str, str] | None = None,
    notes: str | None = None,
) -> str:
    """Merge profile fields into the human block without clobbering other lines."""
    prefs = dict(preferences or {})
    # Normalize canonical keys
    for src, canon in (
        ("city", CITY_KEY),
        ("City", CITY_KEY),
        ("timezone", TIMEZONE_KEY),
        ("Timezone", TIMEZONE_KEY),
        ("tz", TIMEZONE_KEY),
    ):
        if src in prefs and canon not in prefs:
            prefs[canon] = prefs.pop(src)
        elif src in prefs and src != canon:
            prefs[canon] = prefs.pop(src)

    lines = [ln for ln in (existing or "").splitlines() if ln.strip()]
    if not lines and not display_name and not prefs and not notes:
        return _DEFAULT_HUMAN

    def _upsert(prefix: str, value: str) -> None:
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
            # Keep Name first when present
            if prefix == NAME_KEY:
                rebuilt.insert(0, f"{prefix}: {value}")
            else:
                rebuilt.append(f"{prefix}: {value}")
        lines = rebuilt

    if display_name:
        _upsert(NAME_KEY, display_name.strip())
    for key, value in prefs.items():
        val = (value or "").strip()
        if not val:
            continue
        _upsert(key, val)
    if notes and notes.strip():
        note = notes.strip()
        if note not in lines:
            lines.append(note)

    text = "\n".join(lines).strip()
    return text or _DEFAULT_HUMAN
