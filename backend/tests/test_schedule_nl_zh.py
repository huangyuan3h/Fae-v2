"""Chinese NL schedule fixtures (Phase Q.4.5)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fae.scheduler.parse_nl import parse_schedule_text

_FIXTURE = Path(__file__).parent / "fixtures" / "schedule_nl_zh.json"


def _cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["text"])
def test_schedule_nl_zh_fixture(case: dict) -> None:
    now = datetime(2026, 7, 19, 12, 0, 0)
    parsed = parse_schedule_text(case["text"], now=now)
    assert parsed.kind == case["kind"]
    assert parsed.run_at is not None
    expected = (now + timedelta(days=int(case["day_offset"]))).replace(
        hour=int(case["hour"]),
        minute=int(case["minute"]),
        second=0,
        microsecond=0,
    )
    assert abs(parsed.run_at - expected.timestamp()) < 1.0
