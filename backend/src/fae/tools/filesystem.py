"""Sandboxed filesystem tools for coding tasks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fae.tools.safepath import WorkspacePathError, safe_resolve

_MAX_READ_BYTES = 200_000
_MAX_SEARCH_RESULTS = 200

FILESYSTEM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file inside the configured workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 2000},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search UTF-8 files in the workspace for a literal string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "glob": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a UTF-8 text file inside the workspace. "
                "Set create_parents=true to create missing parent directories; "
                "use this instead of mkdir when creating a new project and its first file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "create_parents": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace one exact text occurrence in a workspace file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
]


def _payload(arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError
    if path.stat().st_size > _MAX_READ_BYTES:
        raise ValueError("file_too_large")
    return path.read_text(encoding="utf-8")


def _search(root: Path, start: Path, query: str, pattern: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    paths = [start] if start.is_file() else start.glob(pattern)
    for path in paths:
        if len(results) >= _MAX_SEARCH_RESULTS:
            break
        try:
            resolved = safe_resolve(root, path)
            text = _read_text(resolved)
        except (WorkspacePathError, FileNotFoundError, UnicodeDecodeError, ValueError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                results.append(
                    {
                        "path": str(resolved.relative_to(root)),
                        "line": line_number,
                        "text": line[:1000],
                    }
                )
                if len(results) >= _MAX_SEARCH_RESULTS:
                    break
    return results


def dispatch_filesystem_tool(
    name: str,
    arguments: str | dict[str, Any],
    *,
    root: str | Path,
) -> str:
    args = _payload(arguments)
    try:
        base = safe_resolve(root, ".")
        if name == "read_file":
            path = safe_resolve(base, str(args.get("path") or ""))
            text = _read_text(path)
            lines = text.splitlines()
            offset = max(1, int(args.get("offset") or 1))
            limit = min(2000, max(1, int(args.get("limit") or 500)))
            selected = lines[offset - 1 : offset - 1 + limit]
            return _json(
                {
                    "ok": True,
                    "path": str(path.relative_to(base)),
                    "offset": offset,
                    "total_lines": len(lines),
                    "content": "\n".join(selected),
                }
            )
        if name == "search_files":
            query = str(args.get("query") or "")
            if not query:
                return _json({"ok": False, "error": "query_required"})
            start = safe_resolve(base, str(args.get("path") or "."))
            if not start.exists():
                return _json({"ok": False, "error": "path_not_found"})
            pattern = str(args.get("glob") or "**/*")
            return _json(
                {
                    "ok": True,
                    "matches": _search(base, start, query, pattern),
                }
            )
        if name == "write_file":
            path = safe_resolve(base, str(args.get("path") or ""))
            if bool(args.get("create_parents")):
                path.parent.mkdir(parents=True, exist_ok=True)
            elif not path.parent.is_dir():
                return _json({"ok": False, "error": "parent_not_found"})
            content = str(args.get("content") or "")
            path.write_text(content, encoding="utf-8")
            return _json({"ok": True, "path": str(path.relative_to(base)), "bytes": len(content.encode())})
        if name == "edit_file":
            path = safe_resolve(base, str(args.get("path") or ""))
            text = _read_text(path)
            old = str(args.get("old_text") or "")
            new = str(args.get("new_text") or "")
            if not old:
                return _json({"ok": False, "error": "old_text_required"})
            count = text.count(old)
            if count == 0:
                return _json({"ok": False, "error": "old_text_not_found"})
            replace_all = bool(args.get("replace_all"))
            if count > 1 and not replace_all:
                return _json({"ok": False, "error": "old_text_not_unique", "matches": count})
            updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
            path.write_text(updated, encoding="utf-8")
            return _json({"ok": True, "path": str(path.relative_to(base)), "replacements": count if replace_all else 1})
        return _json({"ok": False, "error": f"unknown tool {name}"})
    except WorkspacePathError as exc:
        return _json({"ok": False, "error": str(exc)})
    except FileNotFoundError:
        return _json({"ok": False, "error": "file_not_found"})
    except UnicodeDecodeError:
        return _json({"ok": False, "error": "not_utf8"})
    except ValueError as exc:
        return _json({"ok": False, "error": str(exc)})
    except OSError as exc:
        return _json({"ok": False, "error": "io_error", "detail": str(exc)})
