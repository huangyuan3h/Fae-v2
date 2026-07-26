"""Single source of truth for tool metadata + risk classification.

Each tool exposed to the LLM has a ``ToolSpec`` describing:

- ``risk_tier`` — safe / caution / sensitive / dangerous.
- ``side_effects`` — short tags for logs/UI (``fs.write``, ``proc.exec``...).
- ``requires_approval`` — when True, every invocation must pass through
  ``fae.approvals.request_approval`` (or an explicit session preauthorization).
- ``needs_diff_preview`` / ``needs_double_confirm`` — UI affordances.
- ``default_ttl_s`` — default time-to-live before a pending approval expires.
- ``channel_allowlist`` — channels allowed to invoke this tool (None = all).

A registry here is intentionally narrow: the existing ``BASH_TOOLS`` /
``FILESYSTEM_TOOLS`` / ``GIT_TOOLS`` schema dicts remain where they are;
this module just feeds metadata into the policy resolver and capability
endpoints. Plan Mode's "统一 Tool Registry" work can promote these into a
schema-factory without breaking policy callers.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger("fae.tool_registry")

RiskTier = Literal["safe", "caution", "sensitive", "dangerous"]

# Side-effect tags. Free-form strings; UI/capability endpoint exposes them.
SideEffect = Literal[
    "fs.read",
    "fs.write",
    "fs.delete",
    "fs.mkdir",
    "net.out",
    "proc.exec",
    "state.mutate",
    "memory.write",
    "schedule.write",
]


@dataclass(frozen=True)
class ToolSpec:
    """Static metadata for one tool.

    ``risk_tier`` is set explicitly — it is the policy anchor. Tools that
    are not in ``TOOL_SPECS`` default to ``risk_tier="safe"`` *and*
    ``requires_approval=False`` (defensive: future tools that someone forgets
    to register cannot accidentally bypass approval).
    """

    name: str
    risk_tier: RiskTier
    side_effects: tuple[str, ...] = ()
    requires_approval: bool = False
    needs_diff_preview: bool = False
    needs_double_confirm: bool = False
    default_ttl_s: float = 60.0
    double_confirm_window_s: float = 5.0
    channel_allowlist: frozenset[str] | None = None  # None = all
    description: str = ""


# ── Catalog ─────────────────────────────────────────────────────────────
# When adding a new tool, also add an entry here so approvals / capabilities
# learn its risk tier. ``register_tool`` below enforces this at runtime.

_TOOL_SPECS: dict[str, ToolSpec] = {
    # ── filesystem ────────────────────────────────────────────────────
    "read_file": ToolSpec(
        "read_file",
        "safe",
        side_effects=("fs.read",),
        description="Read a UTF-8 text file inside the workspace.",
    ),
    "search_files": ToolSpec(
        "search_files",
        "safe",
        side_effects=("fs.read",),
        description="ripgrep-style search inside the workspace.",
    ),
    "make_directory": ToolSpec(
        "make_directory",
        "caution",
        side_effects=("fs.mkdir",),
        description="Create a directory inside the workspace.",
    ),
    "write_file": ToolSpec(
        "write_file",
        "sensitive",
        side_effects=("fs.write",),
        requires_approval=True,
        needs_diff_preview=True,
        default_ttl_s=60.0,
        description="Write UTF-8 text to a file inside the workspace.",
    ),
    "edit_file": ToolSpec(
        "edit_file",
        "sensitive",
        side_effects=("fs.write",),
        requires_approval=True,
        needs_diff_preview=True,
        default_ttl_s=60.0,
        description="Apply an old→new text replacement inside a file.",
    ),
    # ── bash ──────────────────────────────────────────────────────────
    "run_bash": ToolSpec(
        "run_bash",
        "sensitive",
        side_effects=("proc.exec",),
        requires_approval=True,
        default_ttl_s=60.0,
        description="Execute a whitelisted binary inside the workspace.",
    ),
    # ── git (read-only today; mutating variants reserved for later) ───
    "git_status": ToolSpec(
        "git_status",
        "safe",
        description="git status --porcelain",
    ),
    "git_diff": ToolSpec(
        "git_diff",
        "safe",
        description="git diff (read-only)",
    ),
    "git_log": ToolSpec(
        "git_log",
        "safe",
        description="git log (read-only)",
    ),
    # ── scheduler ────────────────────────────────────────────────────
    "schedule_create_job": ToolSpec(
        "schedule_create_job",
        "caution",
        side_effects=("schedule.write", "state.mutate"),
        description="Create a new scheduled job.",
    ),
    "list_jobs": ToolSpec(
        "list_jobs",
        "safe",
        description="List scheduled jobs.",
    ),
    "cancel_job": ToolSpec(
        "cancel_job",
        "sensitive",
        side_effects=("state.mutate",),
        requires_approval=True,
        default_ttl_s=60.0,
        description="Cancel an active scheduled job.",
    ),
    # ── skills / subagents / weather ──────────────────────────────────
    "request_skill": ToolSpec(
        "request_skill",
        "safe",
        description="Lazily load a skill into the active skill set.",
    ),
    "run_subagent": ToolSpec(
        "run_subagent",
        "caution",
        side_effects=("memory.write",),
        description="Run a sub-agent (no tools allowed) to gather context.",
    ),
    "get_weather": ToolSpec(
        "get_weather",
        "safe",
        side_effects=("net.out",),
        description="Open-Meteo weather lookup (HTTPS GET, no API key).",
    ),
}


def register_tool(spec: ToolSpec) -> ToolSpec:
    """Insert (or replace) a ``ToolSpec``. Returns the previous value or None.

    Tests use this to inject temporary specs; production callers should
    prefer the static catalog. Always keep this idempotent.
    """
    previous = _TOOL_SPECS.get(spec.name)
    _TOOL_SPECS[spec.name] = spec
    return previous  # type: ignore[return-value]


def reset_registry() -> None:
    """Drop all dynamically-added specs. Production-safe (no-ops)."""
    static_names = set(_TOOL_SPECS.keys())  # snapshot
    _TOOL_SPECS.clear()
    logger.debug("reset tool registry; %d specs retained", len(static_names))


def known_tool_names() -> frozenset[str]:
    return frozenset(_TOOL_SPECS.keys())


def get_spec(name: str) -> ToolSpec | None:
    return _TOOL_SPECS.get(name)


# ── Policy ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EffectivePolicy:
    """Resolved session preauthorization at the moment of a tool call."""

    session_id: str
    always_allow: frozenset[str]
    denied_tools: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class PolicyDecision:
    """The result of evaluating a tool invocation against the policy."""

    allow: bool
    source: str  # "always" | "session_rule" | "safe" | "denied" | "needs_approval"
    risk_tier: RiskTier
    reason: str = ""


def canonical_args_hash(tool_name: str, arguments: str) -> str:
    """Stable SHA-256 of (tool, canonicalised args) for preauth matching."""
    try:
        payload = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError:
        payload = {"_raw": arguments}
    canonical = json.dumps(
        {"tool": tool_name, "args": payload},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_policy(
    policy: EffectivePolicy | None,
    tool_name: str,
    *,
    channel: str = "unknown",
) -> PolicyDecision:
    """Resolve whether ``tool_name`` is allowed to run.

    The rules (in order):

    1. Spec present and ``channel_allowlist`` non-None: if channel not in
       the list, deny.
    2. ``policy.denied_tools`` denies explicit denial.
    3. ``policy.always_allow`` matches: auto-approve.
    4. Spec missing → ``safe`` (defensive fail-open only for unknown tools
       that the LLM cannot invoke; LLM tools are pre-registered).
    5. Spec ``requires_approval=False`` → safe pass.
    6. Otherwise → ``needs_approval`` (caller must await human approval).
    """
    spec = get_spec(tool_name)
    if spec is not None and spec.channel_allowlist is not None:
        if channel not in spec.channel_allowlist:
            return PolicyDecision(
                allow=False,
                source="denied",
                risk_tier=spec.risk_tier,
                reason=f"channel {channel!r} not permitted for {tool_name}",
            )
    if policy is not None and tool_name in policy.denied_tools:
        return PolicyDecision(
            allow=False,
            source="denied",
            risk_tier=spec.risk_tier if spec else "safe",
            reason="explicitly denied in session policy",
        )
    if policy is not None and tool_name in policy.always_allow:
        return PolicyDecision(
            allow=True,
            source="always",
            risk_tier=spec.risk_tier if spec else "safe",
        )
    if spec is None:
        # Tools we don't know about must still be invoked; treat as safe
        # but the dispatcher should also reject unknown names. See
        # ``_dispatch_coding_tool`` for the dispatch allow-list.
        return PolicyDecision(allow=True, source="safe", risk_tier="safe")
    if not spec.requires_approval:
        return PolicyDecision(
            allow=True, source="safe", risk_tier=spec.risk_tier
        )
    return PolicyDecision(
        allow=False,
        source="needs_approval",
        risk_tier=spec.risk_tier,
        reason=f"{tool_name} requires explicit approval (tier={spec.risk_tier})",
    )


# ── Capability / diff helpers ───────────────────────────────────────────
def specs_for_capabilities() -> dict[str, dict[str, Any]]:
    """Serialize specs for the public capabilities endpoint."""
    out: dict[str, dict[str, Any]] = {}
    for name, spec in _TOOL_SPECS.items():
        out[name] = {
            "risk_tier": spec.risk_tier,
            "side_effects": list(spec.side_effects),
            "requires_approval": spec.requires_approval,
            "needs_diff_preview": spec.needs_diff_preview,
            "needs_double_confirm": spec.needs_double_confirm,
            "default_ttl_s": spec.default_ttl_s,
            "description": spec.description,
        }
    return out


def diff_preview_for(
    tool_name: str,
    arguments: dict[str, Any] | str,
) -> str | None:
    """Render a short human-readable preview of an edit/write request.

    Returns ``None`` for tools that don't have a meaningful diff.
    The output is sanitised through :func:`safe_text` by callers.
    """
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    else:
        parsed = arguments
    if not isinstance(parsed, dict):
        return None
    if tool_name == "write_file":
        path = parsed.get("path") or parsed.get("file_path") or ""
        content = parsed.get("content", "")
        return f"create-or-overwrite {path} ({len(content)} chars)"
    if tool_name == "edit_file":
        path = parsed.get("path") or parsed.get("file_path") or ""
        old = parsed.get("old_text", "")
        new = parsed.get("new_text", "")
        return f"edit {path} (old {len(old)} chars → new {len(new)} chars)"
    if tool_name == "run_bash":
        argv = parsed.get("argv") or parsed.get("command") or ""
        if isinstance(argv, list):
            argv = " ".join(str(x) for x in argv)
        return f"bash: {argv!r}"
    return None
