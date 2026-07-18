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
    # remote | embedded | off
    letta_mode: str = Field(default="remote", description="remote | embedded | off")
    letta_server_url: str = "http://localhost:8283"
    letta_agent_name: str = "fae-main"
    letta_server_password: str = ""
    # Relative to repo root unless absolute
    letta_embedded_path: str = ".data/fae-memory.db"
    recall_db_path: str = ".data/fae-recall.db"
    recall_max_turns: int = Field(default=30, ge=2, description="Hot recall window")
    recall_compact_batch: int = Field(default=10, ge=1)
    core_current_char_limit: int = Field(default=2000, ge=200)
    # Force stub archival even if Qdrant is up (tests / offline)
    archival_prefer_stub: bool = False

    # Sleeptime consolidation (Phase 2.4)
    sleeptime_enabled: bool = True
    sleeptime_idle_seconds: int = Field(default=300, ge=5)
    sleeptime_poll_seconds: int = Field(default=30, ge=1)
    sleeptime_max_runtime_s: float = Field(default=30.0, ge=1.0)
    sleeptime_min_interval_s: float = Field(default=60.0, ge=0.0)
    # Local hour (0-23) for daily pass; None disables the daily trigger
    sleeptime_daily_hour: int | None = 3

    # vLLM self-hosted (optional)
    vllm_asr_url: str = "http://localhost:8001"
    vllm_llm_url: str = "http://localhost:8002"

    # Vector store
    qdrant_url: str = "http://localhost:6333"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # CORS — comma-separated origins for the Next.js UI
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Optional Daily API key for future WebRTC / Pipecat transport
    daily_api_key: str = ""

    # Security
    secret_key: str = "change-me"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor.

    Caching avoids re-parsing .env on every request. Tests can call
    `get_settings.cache_clear()` to pick up env changes.
    """
    return Settings()
