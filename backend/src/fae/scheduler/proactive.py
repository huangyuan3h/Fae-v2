"""Outreach eligibility rules (Phase 4 / Q.4).

Scheduler layer owns "max 1/day" and idle thresholds.
Skill ``proactive_outreach`` cooldown (12h) is enforced via SkillRuntime.activate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutreachPolicy:
    """Defaults match DEVELOPMENT_PLAN Phase 4.1."""

    idle_seconds: float = 6 * 3600
    cooldown_seconds: float = 12 * 3600
    max_per_day: int = 1
    skill_name: str = "proactive_outreach"


def should_outreach(
    *,
    idle_seconds: float | None,
    seconds_since_last_outreach: float | None,
    outreach_count_today: int,
    has_open_topic: bool,
    policy: OutreachPolicy | None = None,
    proactive_enabled: bool = True,
    in_quiet_hours: bool = False,
) -> bool:
    """Return True when a proactive greeting may fire.

    Quiet hours and ``proactive_enabled`` suppress generation entirely
    (not only desktop/push delivery).
    """
    if not proactive_enabled or in_quiet_hours:
        return False
    p = policy or OutreachPolicy()
    if not has_open_topic:
        return False
    if idle_seconds is None or idle_seconds < p.idle_seconds:
        return False
    if outreach_count_today >= p.max_per_day:
        return False
    if (
        seconds_since_last_outreach is not None
        and seconds_since_last_outreach < p.cooldown_seconds
    ):
        return False
    return True
