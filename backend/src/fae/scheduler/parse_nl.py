"""Lightweight natural-language → schedule job parsing (zh / en)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal


@dataclass
class ParsedSchedule:
    kind: Literal["cron", "date"]
    title: str
    body: str
    cron: str | None = None
    run_at: float | None = None
    raw_text: str = ""


_CRON_RE = re.compile(
    r"^(\S+\s+\S+\s+\S+\s+\S+\s+\S+)$"
)

# 每天 8:00 / every day at 8am
_DAILY_ZH = re.compile(
    r"(?:每天|每日)\s*(\d{1,2})\s*[点:：]?\s*(\d{0,2})",
    re.I,
)
_DAILY_EN = re.compile(
    r"(?:every\s+day|daily)\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
    re.I,
)

# 明天 / 明早 / tomorrow
_TOMORROW_ZH = re.compile(
    r"(明天|明早|明日)\s*(\d{1,2})\s*[点:：]?\s*(\d{0,2})?",
)
_TOMORROW_EN = re.compile(
    r"tomorrow\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
    re.I,
)

# 今天下午 3 点 / today at 3pm
_TODAY_ZH = re.compile(
    r"(今天|今晚)\s*(上午|下午|晚上)?\s*(\d{1,2})\s*[点:：]?\s*(\d{0,2})?",
)
_TODAY_EN = re.compile(
    r"today\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
    re.I,
)

# in N minutes / N 分钟后
_REL_MIN = re.compile(
    r"(?:(\d+)\s*(?:分钟|分|min(?:ute)?s?)\s*(?:后|之后)?|"
    r"in\s+(\d+)\s*min(?:ute)?s?)",
    re.I,
)

_REMIND_STRIP = re.compile(
    r"^(提醒我|提醒|记得|please\s+remind\s+me\s+to|remind\s+me\s+to)\s*",
    re.I,
)


def _ampm_hour(hour: int, ampm: str | None) -> int:
    if ampm is None:
        return hour % 24
    ampm = ampm.lower()
    if ampm == "pm" and hour < 12:
        return hour + 12
    if ampm == "am" and hour == 12:
        return 0
    return hour % 24


def _zh_period_hour(hour: int, period: str | None) -> int:
    if period in ("下午", "晚上") and hour < 12:
        return hour + 12
    if period == "上午" and hour == 12:
        return 0
    return hour % 24


def _extract_title(text: str) -> str:
    t = text.strip()
    # Drop time phrases to leave the reminder body as title
    t = re.sub(
        r"(明天|明早|明日|今天|今晚|每天|每日|tomorrow|today|every\s+day|daily)"
        r"[^\u4e00-\u9fff\w]*",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"\d{1,2}\s*[点:：:]\s*\d{0,2}\s*(am|pm)?", "", t, flags=re.I)
    t = re.sub(r"\d{1,2}\s*(am|pm)", "", t, flags=re.I)
    t = _REMIND_STRIP.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" ，,。.")
    return t or text.strip()[:80]


def parse_schedule_text(
    text: str,
    *,
    now: datetime | None = None,
) -> ParsedSchedule:
    """Parse user NL into a schedule. Raises ValueError if unparseable."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty schedule text")

    # Raw 5-field cron
    if _CRON_RE.match(raw):
        return ParsedSchedule(
            kind="cron",
            title="cron job",
            body=raw,
            cron=raw,
            raw_text=raw,
        )

    base = now or datetime.now().astimezone()
    title = _extract_title(raw)

    m = _REL_MIN.search(raw)
    if m:
        mins = int(m.group(1) or m.group(2) or "0")
        run = base + timedelta(minutes=mins)
        return ParsedSchedule(
            kind="date",
            title=title,
            body=raw,
            run_at=run.timestamp(),
            raw_text=raw,
        )

    m = _DAILY_ZH.search(raw)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or "0") or 0
        cron = f"{minute} {hour} * * *"
        return ParsedSchedule(
            kind="cron",
            title=title,
            body=raw,
            cron=cron,
            raw_text=raw,
        )

    m = _DAILY_EN.search(raw)
    if m:
        hour = _ampm_hour(int(m.group(1)), m.group(3))
        minute = int(m.group(2) or "0")
        cron = f"{minute} {hour} * * *"
        return ParsedSchedule(
            kind="cron",
            title=title,
            body=raw,
            cron=cron,
            raw_text=raw,
        )

    m = _TOMORROW_ZH.search(raw)
    if m:
        hour = int(m.group(2))
        minute = int(m.group(3) or "0") or 0
        # 明早 implies morning if hour small; keep as-is
        day = (base + timedelta(days=1)).replace(
            hour=hour % 24, minute=minute, second=0, microsecond=0
        )
        return ParsedSchedule(
            kind="date",
            title=title,
            body=raw,
            run_at=day.timestamp(),
            raw_text=raw,
        )

    m = _TOMORROW_EN.search(raw)
    if m:
        hour = _ampm_hour(int(m.group(1)), m.group(3))
        minute = int(m.group(2) or "0")
        day = (base + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        return ParsedSchedule(
            kind="date",
            title=title,
            body=raw,
            run_at=day.timestamp(),
            raw_text=raw,
        )

    m = _TODAY_ZH.search(raw)
    if m:
        period = m.group(2)
        hour = _zh_period_hour(int(m.group(3)), period)
        minute = int(m.group(4) or "0") or 0
        day = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day <= base:
            day += timedelta(days=1)
        return ParsedSchedule(
            kind="date",
            title=title,
            body=raw,
            run_at=day.timestamp(),
            raw_text=raw,
        )

    m = _TODAY_EN.search(raw)
    if m:
        hour = _ampm_hour(int(m.group(1)), m.group(3))
        minute = int(m.group(2) or "0")
        day = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day <= base:
            day += timedelta(days=1)
        return ParsedSchedule(
            kind="date",
            title=title,
            body=raw,
            run_at=day.timestamp(),
            raw_text=raw,
        )

    # "明早8点提醒吃维生素" without space — already covered by _TOMORROW_ZH
    # Fallback: HH:MM today/tomorrow
    m = re.search(r"(\d{1,2})[点:：](\d{2})", raw)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        day = base.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
        if "明天" in raw or "明早" in raw or "tomorrow" in raw.lower():
            day = day + timedelta(days=1)
            day = day.replace(hour=hour % 24, minute=minute)
        elif day <= base:
            day += timedelta(days=1)
        return ParsedSchedule(
            kind="date",
            title=title,
            body=raw,
            run_at=day.timestamp(),
            raw_text=raw,
        )

    raise ValueError(f"could not parse schedule: {raw!r}")
