"""Resolve repo-root evals/ from backend/tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_ROOT = REPO_ROOT / "evals"


def evals_path(*parts: str) -> Path:
    return EVALS_ROOT.joinpath(*parts)
