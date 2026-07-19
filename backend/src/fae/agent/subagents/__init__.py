"""Lightweight subagent delegation (Phase 5.2). Not a multi-agent product."""

from fae.agent.subagents.builtins import list_builtin_names
from fae.agent.subagents.runtime import SubagentResult, run_subagent
from fae.agent.subagents.tools import RUN_SUBAGENT_TOOL, dispatch_run_subagent

__all__ = [
    "RUN_SUBAGENT_TOOL",
    "SubagentResult",
    "dispatch_run_subagent",
    "list_builtin_names",
    "run_subagent",
]
