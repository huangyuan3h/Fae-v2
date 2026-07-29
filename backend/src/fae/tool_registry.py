"""Single source of truth for tool metadata, risk classification, and OpenAI schemas.

The registry owns:

- Static ``ToolSpec`` catalog (name / group / schema / risk tier / approval policy).
- Plugin-style ``register_tool(spec)`` and idempotent ``reset_registry()``.
- Discovery helpers: ``known_tool_names``, ``groups``, ``specs_in_group``,
  ``iter_openai_schemas(group=...)``.
- Policy resolution: ``EffectivePolicy``, ``PolicyDecision``,
  ``resolve_policy(policy, name, channel=...)``.
- Capability/diff helpers: ``specs_for_capabilities``, ``diff_preview_for``,
  ``canonical_args_hash``.

OpenAI-style tool **schemas** live in their feature modules
(``fae.tools.{filesystem,bash,git,weather}``, ``fae.scheduler.tools``,
``fae.agent.subagents.tools``, ``fae.agent.skills_runtime``) so each module
remains self-contained. The registry imports these schema lists at import
time and pairs them with policy metadata, making it the single place to
declare a tool's risk tier and approval requirements.

Domain dispatchers (``dispatch_filesystem_tool`` / ``dispatch_bash_tool`` / ...)
remain in their respective modules because each has distinct context
dependencies (sync vs async, executor pool, schedule store, subagent runtime).
What this module unifies is the *registration + metadata* surface; dispatch
composition is intentionally left untouched.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

logger = logging.getLogger("fae.tool_registry")

RiskTier = Literal["safe", "caution", "sensitive", "dangerous"]

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


# Group labels — kept as module-level constants so external callers can do
# ``group in CODING_GROUPS`` instead of repeating the literal set.
CODING_GROUPS: frozenset[str] = frozenset({"filesystem", "bash", "git"})

# Default timeout (seconds) applied when a spec has no ``default_timeout_s``.
# Per-tool defaults live on the spec; call sites may also override via
# ``resolve_timeout(name, override=...)``.
DEFAULT_TOOL_TIMEOUT_S: float = 30.0


def _openai_tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Construct an OpenAI-style tool entry from its components."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


@dataclass(frozen=True)
class ToolSpec:
    """Static metadata + OpenAI schema for one tool.

    ``risk_tier`` is the policy anchor. ``group`` is a routing label that maps
    to a feature module (filesystem / bash / git / weather / schedule /
    subagent / skill); the LLM-facing schema list is built by iterating
    ``specs_in_group(g)``. ``schema`` is the OpenAI ``function`` body —
    ``{name, description, parameters}`` — and is the single source of truth
    that flows back out via ``to_openai()``.
    """

    name: str
    risk_tier: RiskTier
    group: str
    schema: dict[str, Any]
    side_effects: tuple[str, ...] = ()
    requires_approval: bool = False
    needs_diff_preview: bool = False
    needs_double_confirm: bool = False
    default_ttl_s: float = 60.0
    double_confirm_window_s: float = 5.0
    default_timeout_s: float | None = None
    channel_allowlist: frozenset[str] | None = None
    output_kind: Literal["text", "json", "markdown"] | None = None
    output_description: str = ""

    @property
    def description(self) -> str:
        return self.schema.get("description", "")

    @property
    def parameters(self) -> dict[str, Any]:
        return self.schema.get("parameters", {"type": "object", "properties": {}})

    def to_openai(self) -> dict[str, Any]:
        return _openai_tool(self.name, self.description, self.parameters)


# ── Catalog ─────────────────────────────────────────────────────────────
_TOOL_SPECS: dict[str, ToolSpec] = {}


def _spec_from(
    schema: dict[str, Any],
    group: str,
    *,
    risk_tier: RiskTier = "safe",
    side_effects: tuple[str, ...] = (),
    requires_approval: bool = False,
    needs_diff_preview: bool = False,
    needs_double_confirm: bool = False,
    default_ttl_s: float = 60.0,
    double_confirm_window_s: float = 5.0,
    default_timeout_s: float | None = None,
    channel_allowlist: frozenset[str] | None = None,
    output_kind: Literal["text", "json", "markdown"] | None = None,
    output_description: str = "",
) -> ToolSpec:
    """Build a ``ToolSpec`` from an OpenAI-style ``{type:function, function:{...}}``.

    ``risk_tier`` and approval metadata are policy decisions; this helper is
    the only place to set them when registering schemas imported from
    feature modules.
    """
    func = schema.get("function")
    if not isinstance(func, dict):
        raise ValueError(f"schema missing 'function' body: {schema!r}")
    name = func.get("name")
    if not name or not isinstance(name, str):
        raise ValueError(f"schema missing 'function.name': {schema!r}")
    return ToolSpec(
        name=name,
        risk_tier=risk_tier,
        group=group,
        schema=dict(func),
        side_effects=side_effects,
        requires_approval=requires_approval,
        needs_diff_preview=needs_diff_preview,
        needs_double_confirm=needs_double_confirm,
        default_ttl_s=default_ttl_s,
        double_confirm_window_s=double_confirm_window_s,
        default_timeout_s=default_timeout_s,
        channel_allowlist=channel_allowlist,
        output_kind=output_kind,
        output_description=output_description,
    )


# Canonical OpenAI schemas for each LLM-callable tool. The ``*_TOOLS`` lists
# are imported lazily inside ``_build_static_catalog`` to avoid an import
# cycle: importing ``fae.scheduler.tools`` pulls in ``fae.scheduler`` which
# transitively imports ``fae.agent`` which imports ``fae.tool_registry``.

_STATIC_BUILT = False
_STATIC_SPECS: dict[str, ToolSpec] = {}
_STATIC_TOOL_NAMES: frozenset[str] = frozenset()


def _build_static_catalog() -> None:
    """Populate ``_TOOL_SPECS`` from each feature module's schema list.

    This is the only place where risk tier / approval metadata is declared
    for built-in tools. Called once, lazily, on first registry access.
    """
    from fae.tools.filesystem import FILESYSTEM_TOOLS as _FS_SCHEMAS
    from fae.tools.bash import BASH_TOOLS as _BASH_SCHEMAS
    from fae.tools.git import GIT_TOOLS as _GIT_SCHEMAS
    from fae.tools.weather import WEATHER_TOOLS as _WEATHER_SCHEMAS
    from fae.scheduler.tools import SCHEDULE_TOOLS as _SCHED_SCHEMAS
    from fae.agent.subagents.tools import RUN_SUBAGENT_TOOL as _SUBAGENT_SCHEMA
    from fae.agent.skills_runtime import REQUEST_SKILL_TOOL as _SKILL_SCHEMA
    from fae.agent.plan_tools import UPDATE_PLAN_TOOL as _PLAN_SCHEMA

    fs_overrides: dict[str, dict[str, Any]] = {
        "read_file": dict(
            risk_tier="safe",
            side_effects=("fs.read",),
            output_kind="text",
            output_description="UTF-8 file contents (truncated to ~2k chars).",
        ),
        "search_files": dict(
            risk_tier="safe",
            side_effects=("fs.read",),
            output_kind="text",
            output_description="Ripgrep-style matches.",
        ),
        "make_directory": dict(
            risk_tier="caution",
            side_effects=("fs.mkdir",),
            output_kind="text",
            output_description="Plain text confirmation of created paths.",
        ),
        "write_file": dict(
            risk_tier="sensitive",
            side_effects=("fs.write",),
            requires_approval=True,
            needs_diff_preview=True,
            output_kind="text",
            output_description="Plain text confirmation of the written file.",
        ),
        "edit_file": dict(
            risk_tier="sensitive",
            side_effects=("fs.write",),
            requires_approval=True,
            needs_diff_preview=True,
            output_kind="text",
            output_description="Plain text confirmation of the replacement.",
        ),
    }
    for schema in _FS_SCHEMAS:
        name = schema["function"]["name"]
        ovr = fs_overrides.get(name)
        if ovr is None:
            logger.warning("filesystem tool %r has no policy override", name)
            continue
        spec = _spec_from(schema, "filesystem", **ovr)
        _TOOL_SPECS[spec.name] = spec

    for schema in _BASH_SCHEMAS:
        spec = _spec_from(
            schema,
            "bash",
            risk_tier="sensitive",
            side_effects=("proc.exec",),
            requires_approval=True,
            default_timeout_s=30.0,
            output_kind="json",
            output_description=(
                "{ok, stdout, stderr, returncode, duration_s} JSON object."
            ),
        )
        _TOOL_SPECS[spec.name] = spec

    for schema in _GIT_SCHEMAS:
        spec = _spec_from(
            schema,
            "git",
            risk_tier="safe",
            default_timeout_s=20.0,
            output_kind="text",
            output_description="Plain text git output.",
        )
        _TOOL_SPECS[spec.name] = spec

    for schema in _WEATHER_SCHEMAS:
        spec = _spec_from(
            schema,
            "weather",
            risk_tier="safe",
            side_effects=("net.out",),
            output_kind="markdown",
            output_description="Current weather + today's forecast as markdown.",
        )
        _TOOL_SPECS[spec.name] = spec

    sched_overrides: dict[str, dict[str, Any]] = {
        "schedule_create_job": dict(
            risk_tier="caution",
            side_effects=("schedule.write", "state.mutate"),
            output_kind="text",
            output_description="Plain text confirmation of the scheduled job.",
        ),
        "list_jobs": dict(
            risk_tier="safe",
            output_kind="json",
            output_description="JSON list of scheduled jobs.",
        ),
        "cancel_job": dict(
            risk_tier="sensitive",
            side_effects=("state.mutate",),
            requires_approval=True,
            output_kind="text",
            output_description="Plain text confirmation of the cancellation.",
        ),
    }
    for schema in _SCHED_SCHEMAS:
        name = schema["function"]["name"]
        ovr = sched_overrides.get(name)
        if ovr is None:
            logger.warning("schedule tool %r has no policy override", name)
            continue
        spec = _spec_from(schema, "schedule", **ovr)
        _TOOL_SPECS[spec.name] = spec

    subagent_spec = _spec_from(
        _SUBAGENT_SCHEMA,
        "subagent",
        risk_tier="caution",
        side_effects=("memory.write",),
        output_kind="text",
        output_description="Citable summary from the sub-agent.",
    )
    _TOOL_SPECS[subagent_spec.name] = subagent_spec

    skill_spec = _spec_from(
        _SKILL_SCHEMA,
        "skill",
        risk_tier="safe",
        output_kind="text",
        output_description="Skill activation confirmation / playbook.",
    )
    _TOOL_SPECS[skill_spec.name] = skill_spec

    plan_spec = _spec_from(
        _PLAN_SCHEMA,
        "plan",
        risk_tier="safe",
        side_effects=("state.mutate",),
        output_kind="text",
        output_description="Plan / plan-step status update confirmation.",
    )
    _TOOL_SPECS[plan_spec.name] = plan_spec


def _ensure_built() -> None:
    global _STATIC_BUILT, _STATIC_SPECS, _STATIC_TOOL_NAMES
    if _STATIC_BUILT:
        return
    _STATIC_BUILT = True
    _build_static_catalog()
    _STATIC_SPECS = dict(_TOOL_SPECS)
    _STATIC_TOOL_NAMES = frozenset(_STATIC_SPECS.keys())


def register_tool(spec: ToolSpec) -> ToolSpec | None:
    """Insert or replace a ``ToolSpec``. Returns the previous spec or None.

    Tests and plugin modules use this to add or override specs at runtime.
    Always keep this idempotent; ``reset_registry`` clears dynamic entries
    but preserves the static catalog.
    """
    _ensure_built()
    previous = _TOOL_SPECS.get(spec.name)
    _TOOL_SPECS[spec.name] = spec
    return previous


def reset_registry() -> None:
    """Drop all dynamically-added specs, preserving the static catalog.

    Production callers should not need this; the registry is fixed at first
    access. Tests use it to revert ad-hoc ``register_tool`` mutations.
    """
    _ensure_built()
    _TOOL_SPECS.clear()
    _TOOL_SPECS.update(_STATIC_SPECS)


def known_tool_names() -> frozenset[str]:
    _ensure_built()
    return frozenset(_TOOL_SPECS.keys())


def static_tool_names() -> frozenset[str]:
    """Names of the built-in (non-dynamic) catalog."""
    _ensure_built()
    return _STATIC_TOOL_NAMES


def get_spec(name: str) -> ToolSpec | None:
    _ensure_built()
    return _TOOL_SPECS.get(name)


def group_for(name: str) -> str | None:
    spec = get_spec(name)
    return spec.group if spec else None


def groups() -> frozenset[str]:
    """Return all registered group identifiers."""
    _ensure_built()
    return frozenset({spec.group for spec in _TOOL_SPECS.values()})


def specs_in_group(group: str) -> tuple[ToolSpec, ...]:
    """Return all specs for a given group (filesystem/bash/git/...)."""
    _ensure_built()
    return tuple(s for s in _TOOL_SPECS.values() if s.group == group)


def iter_openai_schemas(group: str | None = None) -> Iterator[dict[str, Any]]:
    """Yield OpenAI-style tool entries for one group (or all)."""
    _ensure_built()
    for spec in _TOOL_SPECS.values():
        if group is None or spec.group == group:
            yield spec.to_openai()


def openai_schema_for(name: str) -> dict[str, Any] | None:
    """Return the OpenAI-style tool entry for a single name, or None."""
    spec = get_spec(name)
    return spec.to_openai() if spec else None


def is_coding_tool(name: str) -> bool:
    """True iff ``name`` lives in a coding group (filesystem / bash / git)."""
    spec = get_spec(name)
    return spec is not None and spec.group in CODING_GROUPS


def resolve_timeout(name: str, override: float | None = None) -> float:
    """Resolve the runtime timeout (seconds) for a tool invocation.

    Precedence: ``override`` (caller-supplied) > spec ``default_timeout_s`` >
    :data:`DEFAULT_TOOL_TIMEOUT_S`. Returns the fallback for unknown tools
    so dispatchers never see ``None``.
    """
    if override is not None:
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    spec = get_spec(name)
    if spec is not None and spec.default_timeout_s is not None:
        return float(spec.default_timeout_s)
    return DEFAULT_TOOL_TIMEOUT_S


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
    source: str  # "always" | "safe" | "denied" | "needs_approval"
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
            "group": spec.group,
            "side_effects": list(spec.side_effects),
            "requires_approval": spec.requires_approval,
            "needs_diff_preview": spec.needs_diff_preview,
            "needs_double_confirm": spec.needs_double_confirm,
            "default_ttl_s": spec.default_ttl_s,
            "default_timeout_s": spec.default_timeout_s,
            "output_kind": spec.output_kind,
            "output_description": spec.output_description,
            "description": spec.description,
            "parameters": spec.parameters,
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
