"""Tests for the unified Tool Registry / policy resolver."""

from __future__ import annotations

import json

import pytest

from fae.tool_registry import (
    CODING_GROUPS,
    DEFAULT_TOOL_TIMEOUT_S,
    EffectivePolicy,
    PolicyDecision,
    ToolSpec,
    canonical_args_hash,
    diff_preview_for,
    get_spec,
    group_for,
    groups,
    is_coding_tool,
    iter_openai_schemas,
    known_tool_names,
    openai_schema_for,
    register_tool,
    reset_registry,
    resolve_policy,
    resolve_timeout,
    specs_for_capabilities,
    specs_in_group,
    static_tool_names,
)


def test_known_tools_matches_dispatch_set() -> None:
    names = known_tool_names()
    assert "write_file" in names
    assert "edit_file" in names
    assert "run_bash" in names
    assert "read_file" in names
    assert "search_files" in names
    assert "get_weather" in names
    assert "request_skill" in names
    assert "run_subagent" in names


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


def _make_spec(
    name: str,
    *,
    risk_tier: str = "dangerous",
    requires_approval: bool = True,
    **kw: object,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        risk_tier=risk_tier,  # type: ignore[arg-type]
        group="test",
        schema={
            "name": name,
            "description": f"test tool {name}",
            "parameters": {"type": "object", "properties": {}},
        },
        requires_approval=requires_approval,
        **kw,
    )


def test_register_tool_overrides() -> None:
    placeholder = register_tool(
        _make_spec(
            "__missing__",
            side_effects=("fs.delete",),
            needs_double_confirm=True,
            double_confirm_window_s=2.5,
            default_ttl_s=20.0,
        )
    )
    assert placeholder is None
    spec = get_spec("__missing__")
    assert spec is not None
    assert spec.risk_tier == "dangerous"
    assert spec.needs_double_confirm is True
    # Clean up via reset (preserves static catalog).
    reset_registry()
    assert get_spec("__missing__") is None
    assert "write_file" in known_tool_names()


def test_groups_and_specs_in_group() -> None:
    g = groups()
    assert {"filesystem", "bash", "git", "weather", "schedule", "subagent", "skill"} <= g

    fs = {s.name for s in specs_in_group("filesystem")}
    assert {"read_file", "search_files", "make_directory", "write_file", "edit_file"} <= fs

    sched = {s.name for s in specs_in_group("schedule")}
    assert {"schedule_create_job", "list_jobs", "cancel_job"} == sched


def test_group_for_known_and_unknown() -> None:
    assert group_for("write_file") == "filesystem"
    assert group_for("run_bash") == "bash"
    assert group_for("does_not_exist") is None


def test_iter_openai_schemas_group_filter() -> None:
    all_names = {
        t["function"]["name"]
        for t in iter_openai_schemas()
    }
    assert {"write_file", "run_bash", "git_diff", "get_weather"} <= all_names

    fs_names = {
        t["function"]["name"] for t in iter_openai_schemas(group="filesystem")
    }
    assert {"read_file", "search_files", "make_directory", "write_file", "edit_file"} == fs_names


def test_openai_schema_for_round_trip() -> None:
    schema = openai_schema_for("write_file")
    assert schema is not None
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "write_file"
    assert "path" in schema["function"]["parameters"]["properties"]

    schema = openai_schema_for("nonexistent")
    assert schema is None


def test_reset_registry_preserves_static_catalog() -> None:
    baseline = known_tool_names()
    register_tool(
        _make_spec("__probe1__", risk_tier="safe", requires_approval=False)
    )
    register_tool(
        _make_spec("__probe2__", risk_tier="safe", requires_approval=False)
    )
    assert {"__probe1__", "__probe2__"} <= known_tool_names()

    reset_registry()
    after = known_tool_names()
    assert after == baseline
    assert get_spec("__probe1__") is None
    assert get_spec("write_file") is not None


def test_static_tool_names_matches_static_catalog() -> None:
    static = static_tool_names()
    assert static
    assert {"write_file", "read_file", "run_bash", "cancel_job"} <= static


def test_spec_parameters_and_description_flow_back() -> None:
    spec = get_spec("write_file")
    assert spec is not None
    assert spec.description  # non-empty
    assert spec.parameters["type"] == "object"
    assert "path" in spec.parameters["properties"]


def test_specs_for_capabilities_includes_group_and_parameters() -> None:
    out = specs_for_capabilities()
    assert out["write_file"]["group"] == "filesystem"
    assert out["write_file"]["parameters"]["type"] == "object"
    assert out["run_bash"]["group"] == "bash"


def test_coding_groups_constant() -> None:
    assert "filesystem" in CODING_GROUPS
    assert "bash" in CODING_GROUPS
    assert "git" in CODING_GROUPS
    assert "weather" not in CODING_GROUPS


def test_is_coding_tool_matches_only_coding_groups() -> None:
    assert is_coding_tool("read_file") is True
    assert is_coding_tool("write_file") is True
    assert is_coding_tool("run_bash") is True
    assert is_coding_tool("git_diff") is True
    assert is_coding_tool("get_weather") is False
    assert is_coding_tool("schedule_create_job") is False
    assert is_coding_tool("run_subagent") is False
    assert is_coding_tool("does_not_exist") is False


def test_resolve_timeout_precedence() -> None:
    # Spec default wins when no override
    assert resolve_timeout("run_bash") == 30.0
    assert resolve_timeout("git_diff") == 20.0

    # Unknown tool falls back to module default
    assert resolve_timeout("__missing__") == DEFAULT_TOOL_TIMEOUT_S

    # Caller override beats both
    assert resolve_timeout("run_bash", override=5.0) == 5.0
    assert resolve_timeout("git_diff", override=None) == 20.0


def test_spec_default_timeout_s_for_proc_and_git() -> None:
    out = specs_for_capabilities()
    assert out["run_bash"]["default_timeout_s"] == 30.0
    assert out["git_status"]["default_timeout_s"] == 20.0
    assert out["git_diff"]["default_timeout_s"] == 20.0
    assert out["git_log"]["default_timeout_s"] == 20.0
    # Filesystem tools don't have a runtime timeout.
    assert out["read_file"]["default_timeout_s"] is None


def test_output_kind_set_for_every_tool() -> None:
    out = specs_for_capabilities()
    expected: dict[str, str] = {
        "read_file": "text",
        "search_files": "text",
        "make_directory": "text",
        "write_file": "text",
        "edit_file": "text",
        "run_bash": "json",
        "git_status": "text",
        "git_diff": "text",
        "git_log": "text",
        "get_weather": "markdown",
        "schedule_create_job": "text",
        "list_jobs": "json",
        "cancel_job": "text",
        "run_subagent": "text",
        "request_skill": "text",
    }
    for name, kind in expected.items():
        assert out[name]["output_kind"] == kind, f"{name} -> {kind}"


def test_output_kind_is_none_for_custom_dynamic_spec() -> None:
    register_tool(
        _make_spec("__nokind__", risk_tier="safe", requires_approval=False)
    )
    try:
        out = specs_for_capabilities()
        assert out["__nokind__"]["output_kind"] is None
        assert out["__nokind__"]["output_description"] == ""
    finally:
        reset_registry()


def test_output_description_present_in_capabilities() -> None:
    out = specs_for_capabilities()
    for name in ("read_file", "run_bash", "get_weather", "list_jobs"):
        assert out[name]["output_description"], f"{name} should have a description"

