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
# 明天早上八点 / 明早八点
_TOMORROW_MORNING_ZH = re.compile(
    r"(明天早上|明天早晨|明早|明天上午)\s*"
    r"([〇零一二三四五六七八九十两\d]{1,3})\s*[点时]"
    r"(?:(\d{1,2}|[〇零一二三四五六七八九十]{1,3})\s*分?)?",
)
# 后天 9 点 / 后天九点
_DAY_AFTER_ZH = re.compile(
    r"后天\s*([〇零一二三四五六七八九十两\d]{1,3})\s*[点时:：]?\s*"
    r"(\d{0,2}|[〇零一二三四五六七八九十]{0,3})?",
)
_TOMORROW_EN = re.compile(
    r"tomorrow\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
    re.I,
)

_ZH_DIGITS = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _zh_numeral_to_int(token: str) -> int | None:
    """Parse simple Chinese hour/minute numerals (八 / 十 / 十二 / 08)."""
    raw = (token or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    if raw == "十":
        return 10
    if raw.startswith("十") and len(raw) == 2 and raw[1] in _ZH_DIGITS:
        return 10 + _ZH_DIGITS[raw[1]]
    if len(raw) == 2 and raw[1] == "十" and raw[0] in _ZH_DIGITS:
        return _ZH_DIGITS[raw[0]] * 10
    if (
        len(raw) == 3
        and raw[1] == "十"
        and raw[0] in _ZH_DIGITS
        and raw[2] in _ZH_DIGITS
    ):
        return _ZH_DIGITS[raw[0]] * 10 + _ZH_DIGITS[raw[2]]
    if len(raw) == 1 and raw in _ZH_DIGITS:
        return _ZH_DIGITS[raw]
    return None

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
        r"(后天|明天早上|明天早晨|明天上午|明天|明早|明日|今天|今晚|每天|每日|"
        r"tomorrow|today|every\s+day|daily)"
        r"[^\u4e00-\u9fff\w]*",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"[〇零一二三四五六七八九十两\d]{1,3}\s*[点时:：]\s*"
        r"(?:\d{0,2}|[〇零一二三四五六七八九十]{0,3})?\s*(分)?\s*(am|pm)?",
        "",
        t,
        flags=re.I,
    )
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

    m = _TOMORROW_MORNING_ZH.search(raw)
    if m:
        hour = _zh_numeral_to_int(m.group(2))
        minute_tok = m.group(3) or ""
        minute = _zh_numeral_to_int(minute_tok) if minute_tok else 0
        if hour is not None and minute is not None:
            day = (base + timedelta(days=1)).replace(
                hour=hour % 24, minute=minute % 60, second=0, microsecond=0
            )
            return ParsedSchedule(
                kind="date",
                title=title,
                body=raw,
                run_at=day.timestamp(),
                raw_text=raw,
            )

    m = _DAY_AFTER_ZH.search(raw)
    if m:
        hour = _zh_numeral_to_int(m.group(1))
        minute_tok = (m.group(2) or "").strip()
        minute = _zh_numeral_to_int(minute_tok) if minute_tok else 0
        if hour is not None and minute is not None:
            day = (base + timedelta(days=2)).replace(
                hour=hour % 24, minute=minute % 60, second=0, microsecond=0
            )
            return ParsedSchedule(
                kind="date",
                title=title,
                body=raw,
                run_at=day.timestamp(),
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
    # Fallback: HH:MM today/tomorrow/day-after
    m = re.search(r"(\d{1,2})[点:：](\d{2})", raw)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        day = base.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
        low = raw.lower()
        if "后天" in raw:
            day = (base + timedelta(days=2)).replace(
                hour=hour % 24, minute=minute, second=0, microsecond=0
            )
        elif "明天" in raw or "明早" in raw or "tomorrow" in low:
            day = (base + timedelta(days=1)).replace(
                hour=hour % 24, minute=minute, second=0, microsecond=0
            )
        elif day <= base:
            day += timedelta(days=1)
        return ParsedSchedule(
            kind="date",
            title=title,
            body=raw,
            run_at=day.timestamp(),
            raw_text=raw,
        )

    # Fallback: Chinese numeral hour with day cue (后天九点开会)
    m = re.search(
        r"([〇零一二三四五六七八九十两]{1,3})\s*[点时]",
        raw,
    )
    if m:
        hour = _zh_numeral_to_int(m.group(1))
        if hour is not None:
            if "后天" in raw:
                offset = 2
            elif "明天" in raw or "明早" in raw:
                offset = 1
            else:
                offset = 0
            day = (base + timedelta(days=offset)).replace(
                hour=hour % 24, minute=0, second=0, microsecond=0
            )
            if offset == 0 and day <= base:
                day += timedelta(days=1)
            return ParsedSchedule(
                kind="date",
                title=title,
                body=raw,
                run_at=day.timestamp(),
                raw_text=raw,
            )

    raise ValueError(f"could not parse schedule: {raw!r}")
