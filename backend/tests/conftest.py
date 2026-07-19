"""Shared pytest fixtures — keep memory off unless a test opts in."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae import config as config_module


@pytest.fixture(autouse=True)
def _memory_off_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LETTA_MODE", "off")
    # Avoid background sleeptime tasks in default app tests.
    monkeypatch.setenv("SLEEPTIME_ENABLED", "false")
    # Skills off by default so FakeProvider chat/stream tests are not
    # consumed by the LAZY request_skill probe round.
    monkeypatch.setenv("SKILLS_ENABLED", "false")
    # Proactive APScheduler off unless a Phase 4 test opts in.
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    # Isolate schedule/notification SQLite per test.
    monkeypatch.setenv("SCHEDULES_DB_PATH", str(tmp_path / "fae-schedules.db"))
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()
