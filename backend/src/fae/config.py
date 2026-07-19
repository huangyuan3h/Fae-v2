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
REPO_ROOT = _REPO_ROOT
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

    # ── Voice / LLM ─────────────────────────────────────────────────────
    # Optional LLM API key (OpenAI-compatible providers, including DashScope chat)
    dashscope_api_key: str = ""
    # Local OpenAI-compatible TTS only (Qwen3-TTS / CosyVoice) — no cloud / browser TTS
    # Optional: mount OpenAI-compatible stub routes on this app (dev wiring only).
    tts_embed_stub: bool = False
    # Upstream TTS server (FAE proxies /api/tts/speak → {url}/audio/speech)
    vllm_tts_url: str = "http://127.0.0.1:8880/v1"
    tts_model: str = "tts-1"
    tts_voice: str = "Vivian"
    tts_language: str = "Chinese"
    tts_speed: float = Field(default=1.2, ge=0.25, le=4.0)
    tts_sample_rate: int = Field(default=24000, ge=8000)
    tts_response_format: str = "wav"
    # Cold start (HF download + model load) on Mac can exceed a minute.
    tts_timeout_s: float = Field(default=300.0, ge=5.0)

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
    # Down-weight archival hits unused for this many days
    archival_decay_days: int = Field(default=180, ge=0)
    episodic_db_path: str = ".data/fae-episodic.db"

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
    # Include 3001: Next.js falls back when 3000 is already taken.
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    )

    # Optional Daily API key for future WebRTC / Pipecat transport
    daily_api_key: str = ""

    # Skills (Phase 3) — markdown playbooks under backend/src/skills
    skills_enabled: bool = True
    skills_dir: str = ""  # empty → default next to package src/skills
    skills_state_path: str = ".data/fae-skills-state.json"
    skills_max_active: int = Field(default=2, ge=1, le=10)

    # Live tools (Open-Meteo weather — no API key)
    weather_enabled: bool = True
    weather_default_city: str = ""
    weather_default_timezone: str = ""

    # Proactive scheduler (Phase 4) — tests should set SCHEDULER_ENABLED=false
    scheduler_enabled: bool = False
    heartbeat_seconds: float = Field(default=30.0, ge=5.0)
    outreach_idle_hours: float = Field(default=6.0, ge=0.5)
    outreach_cooldown_hours: float = Field(default=12.0, ge=1.0)
    outreach_max_per_day: int = Field(default=1, ge=0)
    schedules_db_path: str = ".data/fae-schedules.db"
    notifications_enabled: bool = True
    # Web Push (Phase 4.4) — optional; empty disables push
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:fae@localhost"

    # Security
    secret_key: str = "change-me"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor.

    Caching avoids re-parsing .env on every request. Tests can call
    `get_settings.cache_clear()` to pick up env changes.
    """
    return Settings()
