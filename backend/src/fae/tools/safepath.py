"""Workspace path validation shared by coding tools."""

from __future__ import annotations

from pathlib import Path


class WorkspacePathError(ValueError):
    pass


def workspace_root(path: str | Path) -> Path:
    raw = str(path).strip()
    if not raw:
        raise WorkspacePathError("workspace_not_configured")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise WorkspacePathError("workspace_not_found")
    return root


def safe_resolve(root: str | Path, path: str | Path) -> Path:
    base = workspace_root(root)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    if resolved != base and base not in resolved.parents:
        raise WorkspacePathError("outside_workspace")
    return resolved
