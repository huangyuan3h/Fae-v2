"""Read-only Git tools for coding tasks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fae.tools.safepath import WorkspacePathError, workspace_root

GIT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show concise Git status for the workspace.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show a read-only Git diff for the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean"},
                    "path": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Show recent Git commits.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            },
        },
    },
]

_MAX_OUTPUT = 30_000


def _payload(arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def dispatch_git_tool(
    name: str,
    arguments: str | dict[str, Any],
    *,
    root: str | Path,
    timeout_s: float = 20.0,
) -> str:
    args = _payload(arguments)
    if name == "git_status":
        argv = ["git", "status", "--short", "--branch"]
    elif name == "git_diff":
        argv = ["git", "diff"]
        if bool(args.get("staged")):
            argv.append("--staged")
        path = str(args.get("path") or "").strip()
        if path:
            argv.extend(["--", path])
    elif name == "git_log":
        limit = min(50, max(1, int(args.get("limit") or 10)))
        argv = ["git", "log", f"-{limit}", "--oneline", "--decorate"]
    else:
        return json.dumps({"ok": False, "error": f"unknown tool {name}"})
    try:
        cwd = workspace_root(root)
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_s)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return json.dumps({"ok": False, "error": "timeout"})
        return json.dumps(
            {
                "ok": process.returncode == 0,
                "exit_code": process.returncode,
                "stdout": stdout.decode("utf-8", errors="replace")[:_MAX_OUTPUT],
                "stderr": stderr.decode("utf-8", errors="replace")[:_MAX_OUTPUT],
                "truncated": len(stdout) > _MAX_OUTPUT or len(stderr) > _MAX_OUTPUT,
            },
            ensure_ascii=False,
        )
    except WorkspacePathError as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    except OSError as exc:
        return json.dumps({"ok": False, "error": "execution_failed", "detail": str(exc)})
