"""Job registry helpers (Phase 4.1 / 4.2).

Builtin cron names match DEVELOPMENT_PLAN:
  - daily_checkin  — 08:00, load daily_check_in skill
  - weekly_recap   — Sunday 20:00
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


BUILTIN_JOB_IDS = ("daily_checkin", "weekly_recap")


@dataclass
class JobSpec:
    id: str
    kind: str  # cron | interval | date
    enabled: bool = True
    cron: str | None = None
    description: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def builtin_job_specs() -> list[JobSpec]:
    return [
        JobSpec(
            id="daily_checkin",
            kind="cron",
            cron="0 8 * * *",
            description="Daily check-in: yesterday memory + daily_check_in skill",
            meta={"skill": "daily_check_in"},
        ),
        JobSpec(
            id="weekly_recap",
            kind="cron",
            cron="0 20 * * sun",
            description="Weekly recap and memory tidy",
        ),
    ]


def list_job_ids(extra: list[JobSpec] | None = None) -> list[str]:
    ids = [j.id for j in builtin_job_specs()]
    for j in extra or []:
        if j.id not in ids:
            ids.append(j.id)
    return ids
