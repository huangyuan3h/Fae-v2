"""Tests for the Tool Registry / policy resolver."""

from __future__ import annotations

import json

import pytest

from fae.tool_registry import (
    EffectivePolicy,
    PolicyDecision,
    canonical_args_hash,
    diff_preview_for,
    get_spec,
    known_tool_names,
    register_tool,
    resolve_policy,
    specs_for_capabilities,
)


def test_known_tools_matches_dispatch_set() -> None:
    names = known_tool_names()
    assert "write_file" in names
    assert "edit_file" in names
    assert "run_bash" in names
    assert "read_file" in names
    assert "search_files" in names
    assert "get_weather" in names


def test_specs_for_capabilities_shape() -> None:
    tools = specs_for_capabilities()
    assert tools["write_file"]["requires_approval"] is True
    assert tools["write_file"]["risk_tier"] == "sensitive"
    assert tools["run_bash"]["requires_approval"] is True
    assert tools["read_file"]["requires_approval"] is False
    assert tools["get_weather"]["requires_approval"] is False


def test_resolve_policy_safe_tools_pass() -> None:
    decision = resolve_policy(None, "read_file", channel="ws")
    assert decision.allow
    assert decision.source == "safe"


def test_resolve_policy_always_allow() -> None:
    policy = EffectivePolicy(
        session_id="s", always_allow=frozenset({"run_bash"})
    )
    decision = resolve_policy(policy, "run_bash", channel="ws")
    assert decision.allow
    assert decision.source == "always"
    assert decision.risk_tier == "sensitive"


def test_resolve_policy_needs_approval() -> None:
    decision = resolve_policy(None, "write_file", channel="ws")
    assert decision.allow is False
    assert decision.source == "needs_approval"
    assert decision.risk_tier == "sensitive"


def test_resolve_policy_deny_explicit() -> None:
    policy = EffectivePolicy(
        session_id="s",
        always_allow=frozenset(),
        denied_tools=frozenset({"run_bash"}),
    )
    decision = resolve_policy(policy, "run_bash", channel="ws")
    assert decision.allow is False
    assert decision.source == "denied"


def test_resolve_policy_channel_allowlist() -> None:
    spec = get_spec("write_file")
    assert spec is not None
    # Mutate temporarily then restore.
    original = spec.channel_allowlist
    object.__setattr__(spec, "channel_allowlist", frozenset({"ws"}))
    try:
        decision = resolve_policy(None, "write_file", channel="telegram")
        assert decision.allow is False
        assert decision.source == "denied"
        ok = resolve_policy(None, "write_file", channel="ws")
        assert ok.source == "needs_approval"
    finally:
        object.__setattr__(spec, "channel_allowlist", original)


def test_canonical_args_hash_stable() -> None:
    args = json.dumps({"path": "x", "content": "y"}, sort_keys=True)
    a = canonical_args_hash("write_file", args)
    b = canonical_args_hash("write_file", json.dumps({"content": "y", "path": "x"}))
    assert a == b
    assert canonical_args_hash("edit_file", args) != a


def test_diff_preview_for_write_file() -> None:
    preview = diff_preview_for(
        "write_file",
        {"path": "src/foo.py", "content": "x" * 16},
    )
    assert preview and "src/foo.py" in preview and "16 chars" in preview


def test_diff_preview_for_run_bash_string_args() -> None:
    preview = diff_preview_for(
        "run_bash",
        json.dumps({"command": "ls -la /tmp"}),
    )
    assert preview and "ls -la /tmp" in preview


def test_register_tool_overrides() -> None:
    placeholder = register_tool(
        type(get_spec("__missing__"))(  # type: ignore[misc]
            name="__missing__",
            risk_tier="dangerous",
            side_effects=("fs.delete",),
            requires_approval=True,
            needs_double_confirm=True,
            double_confirm_window_s=2.5,
            default_ttl_s=20.0,
        )
        if get_spec("__missing__") else __import__(
            "fae.tool_registry", fromlist=["ToolSpec"]
        ).ToolSpec(
            name="__missing__",
            risk_tier="dangerous",
            side_effects=("fs.delete",),
            requires_approval=True,
            needs_double_confirm=True,
            double_confirm_window_s=2.5,
            default_ttl_s=20.0,
        )
    )
    spec = get_spec("__missing__")
    assert spec is not None
    assert spec.risk_tier == "dangerous"
    assert spec.needs_double_confirm is True
    # Clean up so subsequent tests don't see a phantom tool.
    from fae.tool_registry import _TOOL_SPECS

    _TOOL_SPECS.pop("__missing__", None)
