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
    # Coding tools off unless a test explicitly opts in; local .env must not
    # add an unexpected tool-probe LLM round to unrelated tests.
    monkeypatch.setenv("CODING_WORKSPACE_ROOT", "")
    monkeypatch.setenv("CODING_FILESYSTEM_ENABLED", "false")
    monkeypatch.setenv("CODING_BASH_ENABLED", "false")
    monkeypatch.setenv("CODING_GIT_ENABLED", "false")
    # Isolate schedule/notification SQLite per test.
    monkeypatch.setenv("SCHEDULES_DB_PATH", str(tmp_path / "fae-schedules.db"))
    monkeypatch.setenv("CHAT_HISTORY_DB_PATH", str(tmp_path / "fae-chat-history.db"))
    monkeypatch.setenv("TOOL_AUDIT_DB_PATH", str(tmp_path / "fae-tool-audit.db"))
    monkeypatch.setenv("AGENT_TRACE_DB_PATH", str(tmp_path / "fae-agent-trace.db"))
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "fae-tasks.db"))
    monkeypatch.setenv("APPROVALS_DB_PATH", str(tmp_path / "fae-approvals.db"))
    monkeypatch.setenv(
        "CHAT_HISTORY_CLEANUP_INTERVAL_S", "3600",
    )
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()
