"""Registry of tool names the agent can actually call (Phase Q.2).

Names are listed explicitly to avoid importing scheduler/tools at module load
(circular import with SkillRuntime → prepare → scheduler).
"""

from __future__ import annotations

# Keep in sync with tool schemas exposed by fae.tools, scheduler tools,
# REQUEST_SKILL_TOOL, and RUN_SUBAGENT_TOOL.
_KNOWN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_weather",
        "schedule_create_job",
        "list_jobs",
        "cancel_job",
        "request_skill",
        "run_subagent",
        "read_file",
        "search_files",
        "make_directory",
        "write_file",
        "edit_file",
        "run_bash",
        "git_status",
        "git_diff",
        "git_log",
    }
)


def known_tool_names() -> frozenset[str]:
    return _KNOWN_TOOL_NAMES
