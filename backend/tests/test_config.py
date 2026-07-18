"""Tests for fae.config — pydantic-settings env loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae import config as config_module
from fae.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Each test gets a fresh Settings instance — env may differ between tests."""
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


def test_defaults_when_no_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings freezes env_file at class definition — subclass with a missing
    # file so the repo-root .env cannot leak into default assertions.
    from pydantic_settings import SettingsConfigDict

    for field in ("APP_ENV", "LOG_LEVEL", "DASHSCOPE_API_KEY", "LETTA_MODE"):
        monkeypatch.delenv(field, raising=False)

    class CleanSettings(Settings):
        model_config = SettingsConfigDict(
            env_file=str(tmp_path / "missing.env"),
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

    s = CleanSettings()
    assert s.app_name == "fae-v2"
    assert s.app_env == "development"
    assert s.log_level == "INFO"
    assert s.dashscope_api_key == ""
    assert s.letta_server_url == "http://localhost:8283"
    assert s.letta_mode == "remote"
    assert s.letta_agent_name == "fae-main"
    assert s.vllm_asr_url == "http://localhost:8001"
    assert s.vllm_llm_url == "http://localhost:8002"
    assert s.qdrant_url == "http://localhost:6333"
    assert s.redis_url == "redis://localhost:6379"
    assert s.secret_key == "change-me"


def test_env_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config_module, "_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv("LETTA_SERVER_URL", "http://letta.example.com:9000")

    s = Settings()
    assert s.app_env == "production"
    assert s.log_level == "DEBUG"
    assert s.dashscope_api_key == "sk-test"
    assert s.letta_server_url == "http://letta.example.com:9000"


def test_env_file_is_loaded(tmp_path: Path) -> None:
    """A .env file at the configured path must be read by Settings.

    pydantic-settings freezes `env_file` at class-definition time, so we
    subclass Settings pointing at our tmp file and verify it loads from
    there rather than the repo-root .env.
    """
    from pydantic_settings import SettingsConfigDict

    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=staging\nDASHSCOPE_API_KEY=sk-from-file\n",
        encoding="utf-8",
    )

    class TmpSettings(Settings):
        model_config = SettingsConfigDict(
            env_file=str(env_file),
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

    s = TmpSettings()
    assert s.app_env == "staging"
    assert s.dashscope_api_key == "sk-from-file"


def test_extra_env_keys_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown env vars must not break settings load (extra='ignore' in config)."""
    monkeypatch.setattr(config_module, "_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("SOMETHING_COMPLETELY_UNRELATED", "noise")

    # Should not raise.
    s = Settings()
    assert s.app_name == "fae-v2"


def test_get_settings_is_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_settings() returns the same instance — caching is by design."""
    monkeypatch.setattr(config_module, "_ENV_FILE", tmp_path / "missing.env")
    a = get_settings()
    b = get_settings()
    assert a is b

    # And cache_clear() forces a reload.
    config_module.get_settings.cache_clear()
    c = get_settings()
    assert c is not a
    # Same field values, but a fresh object.
    assert c.app_name == a.app_name
