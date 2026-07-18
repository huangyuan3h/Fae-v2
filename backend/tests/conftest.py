"""Shared pytest fixtures — keep memory off unless a test opts in."""

from __future__ import annotations

import pytest

from fae import config as config_module


@pytest.fixture(autouse=True)
def _memory_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LETTA_MODE", "off")
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()
