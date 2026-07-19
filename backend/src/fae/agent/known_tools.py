"""Registry of tool names the agent can actually call (Phase Q.2).

Names are listed explicitly to avoid importing scheduler/tools at module load
(circular import with SkillRuntime → prepare → scheduler).
"""

from __future__ import annotations

# Keep in sync with WEATHER_TOOLS / SCHEDULE_TOOLS / REQUEST_SKILL_TOOL /
# RUN_SUBAGENT_TOOL.
_KNOWN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_weather",
        "schedule_create_job",
        "list_jobs",
        "cancel_job",
        "request_skill",
        "run_subagent",
    }
)


def known_tool_names() -> frozenset[str]:
    return _KNOWN_TOOL_NAMES
