"""Application configuration loaded from environment / .env file.

Single source of truth for runtime settings. Other modules import `settings`
and never read `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve .env relative to the repo root (one level above backend/), so the
# same .env works whether you run from backend/ or from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Runtime settings.

    Add new fields here as the project grows. Keep them typed so misconfig
    fails fast at startup instead of mid-request.
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ─────────────────────────────────────────────────────────────
    app_name: str = "fae-v2"
    app_env: str = Field(default="development", description="development | production")
    log_level: str = "INFO"

    # ── Voice / LLM (placeholders for later checkpoints) ────────────────
    # DashScope (Qwen3-TTS Realtime + Qwen3 LLM)
    dashscope_api_key: str = ""

    # Letta (long-term memory)
    letta_server_url: str = "http://localhost:8283"

    # vLLM self-hosted (optional)
    vllm_asr_url: str = "http://localhost:8001"
    vllm_llm_url: str = "http://localhost:8002"

    # Vector store
    qdrant_url: str = "http://localhost:6333"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Security
    secret_key: str = "change-me"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor.

    Caching avoids re-parsing .env on every request. Tests can call
    `get_settings.cache_clear()` to pick up env changes.
    """
    return Settings()
