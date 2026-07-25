"""Tests for sandboxed coding tools."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from fae.tools.bash import dispatch_bash_tool
from fae.tools.filesystem import dispatch_filesystem_tool
from fae.tools.git import dispatch_git_tool


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
