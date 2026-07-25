"""Restricted shell execution for coding tasks."""

from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path
from typing import Any

from fae.tools.safepath import WorkspacePathError, workspace_root

BASH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": (
                "Run one allowlisted command in the workspace without shell expansion. "
                "Use write_file with create_parents=true instead of mkdir; use this tool "
                "for builds, tests, and executing code after files have been written."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_s": {"type": "number", "minimum": 1, "maximum": 120},
                },
                "required": ["command"],
            },
        },
    }
]

_ALLOWED_COMMANDS = frozenset(
    {
        "ls",
        "pwd",
        "python",
        "python3",
        "pytest",
        "uv",
        "npm",
        "npx",
        "pnpm",
        "node",
        "ruff",
        "mypy",
        "tsc",
    }
)
_MAX_OUTPUT = 20_000


def _payload(arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def dispatch_bash_tool(
    name: str,
    arguments: str | dict[str, Any],
    *,
    root: str | Path,
    timeout_s: float = 30.0,
) -> str:
    if name != "run_bash":
        return json.dumps({"ok": False, "error": f"unknown tool {name}"})
    args = _payload(arguments)
    command = str(args.get("command") or "").strip()
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": "invalid_command", "detail": str(exc)})
    if not argv:
        return json.dumps({"ok": False, "error": "command_required"})
    executable = Path(argv[0]).name
    if executable not in _ALLOWED_COMMANDS:
        return json.dumps({"ok": False, "error": "command_not_allowed", "command": executable})
    try:
        cwd = workspace_root(root)
        requested_timeout = float(args.get("timeout_s") or timeout_s)
        effective_timeout = min(120.0, max(1.0, requested_timeout, 0.0), max(1.0, timeout_s))
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), effective_timeout)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return json.dumps({"ok": False, "error": "timeout", "timeout_s": effective_timeout})
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
