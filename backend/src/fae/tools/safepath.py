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


def _resolve_extra_root(value: str | Path | None) -> Path | None:
    """Best-effort resolve one extra root; silently skip empty / non-dirs."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        root = Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    return root if root.is_dir() else None


def safe_resolve(
    root: str | Path,
    path: str | Path,
    *,
    extra_roots: tuple[str | Path, ...] = (),
) -> Path:
    """Resolve ``path`` against ``root`` (or one of ``extra_roots``).

    Rules:
    - Empty ``root`` raises ``workspace_not_configured`` (the primary
      filesystem root must be configured before coding tools are enabled).
    - ``path`` is allowed if it resolves to ``root`` itself, anywhere
      inside ``root``, or anywhere inside any of ``extra_roots``.
    - ``extra_roots`` that are empty / non-existent are silently skipped
      so callers can pass settings unconditionally.
    """
    base = workspace_root(root)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    allowed: list[Path] = [base]
    for extra in extra_roots:
        extra_root = _resolve_extra_root(extra)
        if extra_root is not None and extra_root not in allowed:
            allowed.append(extra_root)
    for allowed_root in allowed:
        if resolved == allowed_root or allowed_root in resolved.parents:
            return resolved
    raise WorkspacePathError("outside_workspace")
