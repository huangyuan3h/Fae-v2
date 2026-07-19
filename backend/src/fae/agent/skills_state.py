"""Persist per-skill enabled / approval / last_triggered overrides."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("fae.agent.skills")


class SkillsStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            self._data = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            logger.exception("failed to load skills state %s", self.path)
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def get(self, name: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._data.get(name, {}))

    def patch(
        self,
        name: str,
        *,
        enabled: bool | None = None,
        requires_approval: bool | None = None,
        last_triggered_at: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            cur = dict(self._data.get(name, {}))
            if enabled is not None:
                cur["enabled"] = enabled
            if requires_approval is not None:
                cur["requires_approval"] = requires_approval
            if last_triggered_at is not None:
                cur["last_triggered_at"] = last_triggered_at
            self._data[name] = cur
            self._save()
            return dict(cur)

    def last_triggered(self, name: str) -> float | None:
        val = self.get(name).get("last_triggered_at")
        return float(val) if isinstance(val, (int, float)) else None
