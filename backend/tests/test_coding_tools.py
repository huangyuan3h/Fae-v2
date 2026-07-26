"""Tests for sandboxed coding tools."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from fae.agent.llm_turn import apply_lazy_skill_tool
from fae.agent.skills_runtime import SkillActivationInfo
from fae.llm import ChatMessage, ChatRequest, LLMClient, LLMConfig, ToolCall
from fae.llm.provider import FakeProvider
from fae.tools.bash import dispatch_bash_tool
from fae.tools.filesystem import dispatch_filesystem_tool
from fae.tools.git import dispatch_git_tool
from fae.tool_registry import EffectivePolicy


def _result(raw: str) -> dict:
    return json.loads(raw)


def test_filesystem_read_search_edit_write(tmp_path: Path) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("value = 1\nprint(value)\n", encoding="utf-8")

    read = _result(dispatch_filesystem_tool("read_file", {"path": "src/main.py"}, root=tmp_path))
    assert read["ok"] is True
    assert "value = 1" in read["content"]

    search = _result(dispatch_filesystem_tool("search_files", {"query": "print", "glob": "**/*.py"}, root=tmp_path))
    assert search["matches"][0]["line"] == 2

    edited = _result(dispatch_filesystem_tool("edit_file", {"path": "src/main.py", "old_text": "value = 1", "new_text": "value = 2"}, root=tmp_path))
    assert edited["ok"] is True
    assert "value = 2" in source.read_text(encoding="utf-8")

    written = _result(dispatch_filesystem_tool("write_file", {"path": "tests/test_main.py", "content": "def test_ok():\n    assert True\n", "create_parents": True}, root=tmp_path))
    assert written["ok"] is True
    assert (tmp_path / "tests" / "test_main.py").is_file()


def test_filesystem_rejects_escape_and_ambiguous_edit(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("same\nsame\n", encoding="utf-8")
    outside = _result(dispatch_filesystem_tool("read_file", {"path": "../secret.txt"}, root=tmp_path))
    assert outside["error"] == "outside_workspace"
    ambiguous = _result(dispatch_filesystem_tool("edit_file", {"path": "target.txt", "old_text": "same", "new_text": "new"}, root=tmp_path))
    assert ambiguous["error"] == "old_text_not_unique"


@pytest.mark.asyncio
async def test_bash_allows_exec_without_shell_and_rejects_unknown(tmp_path: Path) -> None:
    allowed = _result(await dispatch_bash_tool("run_bash", {"command": "python -c 'print(2 + 2)'"}, root=tmp_path))
    assert allowed["ok"] is True
    assert allowed["stdout"].strip() == "4"
    rejected = _result(await dispatch_bash_tool("run_bash", {"command": "rm -rf ."}, root=tmp_path))
    assert rejected["error"] == "command_not_allowed"


@pytest.mark.asyncio
async def test_bash_supports_safe_cwd_and_basic_commands(tmp_path: Path) -> None:
    project = tmp_path / "test-fae"
    project.mkdir()
    (project / "hello.js").write_text('console.log("hello")\n', encoding="utf-8")
    result = _result(
        await dispatch_bash_tool(
            "run_bash",
            {"command": "node hello.js", "cwd": "test-fae"},
            root=tmp_path,
        )
    )
    assert result["ok"] is True
    assert result["stdout"].strip() == "hello"
    escaped = _result(
        await dispatch_bash_tool(
            "run_bash",
            {"command": "pwd", "cwd": "../"},
            root=tmp_path,
        )
    )
    assert escaped["error"] == "outside_workspace"


def test_make_directory_tool(tmp_path: Path) -> None:
    result = _result(
        dispatch_filesystem_tool(
            "make_directory",
            {"paths": ["one/two", "three"]},
            root=tmp_path,
        )
    )
    assert result["ok"] is True
    assert (tmp_path / "one" / "two").is_dir()
    assert (tmp_path / "three").is_dir()


@pytest.mark.asyncio
async def test_git_tools_are_read_only(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")

    status = _result(await dispatch_git_tool("git_status", {}, root=tmp_path))
    diff = _result(await dispatch_git_tool("git_diff", {}, root=tmp_path))
    log = _result(await dispatch_git_tool("git_log", {"limit": 1}, root=tmp_path))
    assert "a.txt" in status["stdout"]
    assert "+two" in diff["stdout"]
    assert "initial" in log["stdout"]


@pytest.mark.asyncio
async def test_coding_tool_loop_writes_then_runs_node(tmp_path: Path) -> None:
    events: list[dict] = []

    async def on_tool_event(event: dict) -> None:
        events.append(event)

    provider = FakeProvider(
        responses=["", "", "Created and verified Hello World."],
        tool_call_responses=[
            [
                ToolCall(
                    id="1",
                    name="write_file",
                    arguments=json.dumps(
                        {
                            "path": "test-fae/helloworld.js",
                            "content": 'console.log("Hello, World!");\n',
                            "create_parents": True,
                        }
                    ),
                )
            ],
            [
                ToolCall(
                    id="2",
                    name="run_bash",
                    arguments=json.dumps(
                        {"command": "node test-fae/helloworld.js"}
                    ),
                )
            ],
            [],
        ],
    )
    request = ChatRequest(
        config=LLMConfig(api_key="k", model="m"),
        messages=[ChatMessage(role="user", content="创建并运行 Node hello world")],
    )
    prepared, _activation, early = await apply_lazy_skill_tool(
        LLMClient(provider),
        request,
        SkillActivationInfo(),
        None,
        workspace_root=str(tmp_path),
        filesystem_enabled=True,
        bash_enabled=True,
        on_tool_event=on_tool_event,
        effective_policy=EffectivePolicy(
            session_id="default",
            always_allow=frozenset({"write_file", "run_bash"}),
        ),
    )

    assert early == "Created and verified Hello World."
    assert (tmp_path / "test-fae" / "helloworld.js").is_file()
    assert len(provider.calls) == 3
    results = [m.content for m in prepared.messages if "tool_result" in m.content]
    assert any("write_file" in result for result in results)
    assert any("Hello, World!" in result for result in results)
    assert [event["phase"] for event in events] == [
        "start",
        "result",
        "start",
        "result",
    ]
    assert all(event["type"] == "tool" for event in events)


def test_write_file_schema_guides_directory_creation() -> None:
    from fae.tools.filesystem import FILESYSTEM_TOOLS

    write_tool = next(
        tool for tool in FILESYSTEM_TOOLS if tool["function"]["name"] == "write_file"
    )
    description = write_tool["function"]["description"]
    assert "create_parents=true" in description
    assert "instead of mkdir" in description
