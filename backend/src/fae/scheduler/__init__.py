"""Proactive loop (Phase 4).

Boundary vs memory consolidation:
  - ``fae.memory.consolidation.SleeptimeScheduler`` — idle/daily memory tidy
  - ``fae.scheduler`` — heartbeat, cron jobs, proactive outreach, notifications

Do not merge the two. Lifespan starts both independently when enabled.
"""

from __future__ import annotations

from fae.scheduler.activity import ActivityTracker
from fae.scheduler.proactive import OutreachPolicy, should_outreach

__all__ = [
    "ActivityTracker",
    "OutreachPolicy",
    "should_outreach",
]
