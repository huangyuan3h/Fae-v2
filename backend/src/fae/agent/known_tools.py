"""Registry of tool names the agent can actually call (Phase Q.2).

The authoritative list lives in :mod:`fae.tool_registry`. This module
re-exports it; ``register_tool()`` on the registry propagates here so the
LLM schema list (``_merge_tools``) and the policy checker always agree.

The cached snapshot is intentionally lazy: ``known_tool_names()`` triggers
the registry's static catalog build, which transitively imports feature
modules. Calling it eagerly at import time would deadlock the partially-
loaded ``fae.agent.skills_runtime`` module.
"""

from __future__ import annotations

from fae.tool_registry import known_tool_names

_KNOWN_TOOL_NAMES: frozenset[str] | None = None


def known_tools() -> frozenset[str]:
    return known_tool_names()


def refresh_known_tools() -> frozenset[str]:
    """Re-pull the authoritative list. Useful in tests after registration."""
    global _KNOWN_TOOL_NAMES
    _KNOWN_TOOL_NAMES = known_tool_names()
    return _KNOWN_TOOL_NAMES
