"""Optional third-party channels (Phase 5.1).

Thin adapters — not a plugin marketplace. Telegram is the first channel.
"""

from fae.channels.bridge import handle_inbound_text, resolve_server_llm_config
from fae.channels.telegram import TelegramClient, telegram_poll_loop, telegram_ready

__all__ = [
    "TelegramClient",
    "handle_inbound_text",
    "resolve_server_llm_config",
    "telegram_poll_loop",
    "telegram_ready",
]
