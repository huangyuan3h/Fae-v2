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
    llm_timeout_s: float = Field(default=60.0, ge=5.0, le=300.0)
    # Local OpenAI-compatible TTS only (Qwen3-TTS / CosyVoice) — no cloud / browser TTS
    # Optional: mount OpenAI-compatible stub routes on this app (dev wiring only).
    tts_embed_stub: bool = False
    # Upstream TTS server (FAE proxies /api/tts/speak → {url}/audio/speech)
    vllm_tts_url: str = "http://127.0.0.1:8880/v1"
    tts_model: str = "tts-1"
    tts_voice: str = "Vivian"
    tts_language: str = "Chinese"
    tts_speed: float = Field(default=1.0, ge=0.25, le=4.0)
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

    # Optional OpenAI-compatible embeddings for archival (empty → hash stub vectors)
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    # Optional fixed output dim (provider-dependent); 0 = use model default
    embedding_dimensions: int = Field(default=0, ge=0)

    # Sleeptime consolidation (Phase 2.4)
    sleeptime_enabled: bool = True
    sleeptime_idle_seconds: int = Field(default=300, ge=5)
    sleeptime_poll_seconds: int = Field(default=30, ge=1)
    sleeptime_max_runtime_s: float = Field(default=30.0, ge=1.0)
    sleeptime_min_interval_s: float = Field(default=60.0, ge=0.0)
    # Local hour (0-23) for daily pass; None disables the daily trigger
    sleeptime_daily_hour: int | None = 3

    # R4: Letta-style reflection subagent for sleeptime consolidation.
    reflection_enabled: bool = True
    reflection_max_task_chars: int = Field(
        default=6000, ge=500,
        description="Max chars of recent turns fed to the reflection subagent.",
    )
    reflection_timeout_s: float = Field(default=20.0, ge=1.0)

    # R2 rolling summary (Context Engineering §8)
    rolling_summary_enabled: bool = True
    rolling_summary_max_turns: int = Field(
        default=30, ge=4,
        description="Hot recall turn count that triggers a rolling summary pass.",
    )
    rolling_summary_max_chars: int = Field(
        default=9000, ge=500,
        description="Estimated char total that triggers a rolling summary pass.",
    )
    rolling_summary_recent_keep: int = Field(
        default=6, ge=1,
        description="Verbatim turns kept at the tail after a summary pass.",
    )
    rolling_summary_timeout_s: float = Field(
        default=20.0, ge=1.0,
        description="Hard cap on the summary LLM call.",
    )

    # vLLM self-hosted (optional)
    vllm_asr_url: str = "http://localhost:8001"
    vllm_llm_url: str = "http://localhost:8002"

    # Vector store
    qdrant_url: str = "http://localhost:6333"

    # Redis
    redis_url: str = "redis://localhost:6379"

    chat_history_db_path: str = ".data/fae-chat-history.db"
    chat_history_retention_days: int = Field(default=7, ge=1, le=3650)
    chat_history_cleanup_interval_s: float = Field(default=3600.0, ge=0.05)

    # Context budgeting — soft caps so the LLM prompt does not silently
    # exceed the model's window. None disables the corresponding check.
    context_window_tokens: int | None = Field(
        default=None,
        ge=512,
        description="Default model context window used for prompt budgeting. "
        "Per-request LLMConfig.context_window overrides this.",
    )
    context_reserve_tokens: int = Field(
        default=2048,
        ge=64,
        description="Tokens reserved for the model's completion (headroom).",
    )
    memory_recent_limit: int = Field(
        default=10, ge=0, le=50,
        description="Number of recent conversation turns injected into the "
        "system block. 0 disables recent turns.",
    )
    memory_events_limit: int = Field(
        default=8, ge=0, le=50,
        description="Max episodic events surfaced per prompt.",
    )
    memory_facts_top_k: int = Field(
        default=10, ge=1, le=50,
        description="Top-k for memory facts search.",
    )

    # CORS — comma-separated origins for the Next.js UI
    # Include 3001: Next.js falls back when 3000 is already taken.
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    )

    # Optional Daily API key for future WebRTC / Pipecat transport
    daily_api_key: str = ""

    # R3 Pipecat LLMContextSummarizer (Daily voice path only).
    daily_context_summary_enabled: bool = False
    daily_context_max_tokens: int = Field(
        default=8000, ge=512,
        description="Daily path token threshold that triggers summarization.",
    )
    daily_context_target_tokens: int = Field(
        default=4000, ge=256,
        description="Daily path summarization target token count.",
    )
    daily_context_recent_messages: int = Field(
        default=4, ge=1,
        description="Daily path: messages kept verbatim after summary.",
    )

    # Skills (Phase 3) — markdown playbooks under backend/src/skills
    skills_enabled: bool = True
    skills_dir: str = ""  # empty → default next to package src/skills
    skills_state_path: str = ".data/fae-skills-state.json"
    skills_max_active: int = Field(default=2, ge=1, le=10)

    # Live tools (Open-Meteo weather — no API key)
    weather_enabled: bool = True
    weather_default_city: str = ""
    weather_default_timezone: str = ""

    # Coding tools — disabled until a workspace root is explicitly configured
    coding_workspace_root: str = ""
    coding_filesystem_enabled: bool = False
    coding_bash_enabled: bool = False
    coding_git_enabled: bool = False
    coding_bash_timeout_s: float = Field(default=30.0, ge=1.0, le=120.0)
    coding_git_timeout_s: float = Field(default=20.0, ge=1.0, le=120.0)

    # Contextual Retrieval (Anthropic §6.3). When enabled, an LLM pass
    # prefixes each archival chunk with a 50–100-token context line so
    # embeddings land closer to the user's actual question. The
    # reference document (e.g. recent recall summary) is sent with
    # cache_control so chunk-contextualization is essentially free.
    contextual_retrieval_enabled: bool = False
    contextual_retrieval_chars: int = Field(
        default=160, ge=40, le=400,
        description="Max chars of contextual prefix added to each chunk.",
    )

# R5 tool-result offload — deep-agents FilesystemMiddleware port
    # (doc/design/CONTEXT_ENGINEERING.md §2). When a tool result exceeds
    # ``tool_offload_chars`` it is dumped to disk under
    # ``tool_offload_dir`` and replaced with a path pointer + first N
    # lines in the prompt. Set to 0 to disable.
    tool_offload_enabled: bool = True
    tool_offload_chars: int = Field(
        default=8000, ge=0,
        description="Char threshold for offloading a tool result to disk.",
    )
    tool_offload_dir: str = ".data/tool-offload"
    tool_offload_keep_lines: int = Field(
        default=20, ge=1,
        description="How many preview lines of the offloaded result to keep.",
    )

    # Proactive scheduler (Phase 4) — tests should set SCHEDULER_ENABLED=false
    scheduler_enabled: bool = False
    heartbeat_seconds: float = Field(default=30.0, ge=5.0)
    outreach_idle_hours: float = Field(default=6.0, ge=0.5)
    outreach_cooldown_hours: float = Field(default=12.0, ge=1.0)
    outreach_max_per_day: int = Field(default=1, ge=0)
    schedules_db_path: str = ".data/fae-schedules.db"
    notifications_enabled: bool = True
    # Server-side LLM for proactive loop (falls back to DASHSCOPE_API_KEY)
    proactive_llm_api_key: str = ""
    proactive_llm_base_url: str = ""
    proactive_llm_model: str = "qwen3-max"
    # Web Push (Phase 4.4) — optional; empty disables push
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:fae@localhost"

    # Telegram channel (Phase 5.1) — long polling; empty token disables
    telegram_enabled: bool = True
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Subagents (Phase 5.2)
    subagent_enabled: bool = True
    subagent_timeout_s: float = Field(default=60.0, ge=5.0, le=600.0)

    # Client auth (P7) — empty disables; when set, required on mutating API / WS
    fae_client_token: str = ""

    # Security
    secret_key: str = "change-me"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor.

    Caching avoids re-parsing .env on every request. Tests can call
    `get_settings.cache_clear()` to pick up env changes.
    """
    return Settings()
