"""Telegram Bot API — long polling inbound + sendMessage outbound."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from fae.config import Settings

logger = logging.getLogger("fae.channels.telegram")

OnText = Callable[[str], Awaitable[str]]


def telegram_ready(settings: Settings) -> bool:
    """True when token + chat_id present and not explicitly disabled."""
    if not getattr(settings, "telegram_enabled", True):
        return False
    token = (getattr(settings, "telegram_bot_token", "") or "").strip()
    chat_id = (getattr(settings, "telegram_chat_id", "") or "").strip()
    return bool(token and chat_id)


class TelegramClient:
    """Minimal Bot API client (getUpdates / sendMessage)."""

    def __init__(
        self,
        token: str,
        *,
        http: httpx.AsyncClient | None = None,
        api_base: str | None = None,
    ) -> None:
        self.token = (token or "").strip()
        if not self.token:
            raise ValueError("telegram bot token required")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        root = (api_base or "https://api.telegram.org").rstrip("/")
        self._base = f"{root}/bot{self.token}"

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def send_message(self, chat_id: str, text: str) -> bool:
        payload_text = (text or "").strip()
        if not payload_text:
            return False
        # Telegram hard limit ~4096; keep a safe margin.
        if len(payload_text) > 4000:
            payload_text = payload_text[:3997] + "..."
        try:
            resp = await self._http.post(
                f"{self._base}/sendMessage",
                json={"chat_id": chat_id, "text": payload_text},
            )
            if resp.status_code >= 400:
                logger.warning(
                    "telegram sendMessage HTTP %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            data = resp.json()
            return bool(data.get("ok"))
        except Exception:  # noqa: BLE001
            logger.debug("telegram sendMessage failed", exc_info=True)
            return False

    async def get_updates(
        self,
        offset: int | None = None,
        *,
        timeout: int = 25,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": max(0, int(timeout)),
            "allowed_updates": ["message"],
        }
        if offset is not None:
            params["offset"] = int(offset)
        resp = await self._http.get(f"{self._base}/getUpdates", params=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            logger.warning("telegram getUpdates not ok: %s", data)
            return []
        result = data.get("result") or []
        return result if isinstance(result, list) else []


def _extract_text(update: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (chat_id, text) from a message update, or (None, None)."""
    msg = update.get("message") or update.get("edited_message")
    if not isinstance(msg, dict):
        return None, None
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None, None
    text = msg.get("text")
    if not isinstance(text, str) or not text.strip():
        return str(chat_id), None
    return str(chat_id), text.strip()


async def telegram_poll_loop(
    client: TelegramClient,
    *,
    allowed_chat_id: str,
    on_text: OnText,
    stop_event: asyncio.Event,
    long_poll_timeout: int = 25,
    error_backoff_s: float = 3.0,
) -> None:
    """Long-poll getUpdates until stop_event is set or task cancelled."""
    allowed = (allowed_chat_id or "").strip()
    if not allowed:
        logger.error("telegram_poll_loop: empty allowed_chat_id")
        return

    offset: int | None = None
    logger.info("Telegram poll loop started (chat_id=%s)", allowed)
    while not stop_event.is_set():
        try:
            updates = await client.get_updates(offset, timeout=long_poll_timeout)
            for upd in updates:
                upd_id = upd.get("update_id")
                if isinstance(upd_id, int):
                    offset = upd_id + 1
                chat_id, text = _extract_text(upd)
                if chat_id is None:
                    continue
                if chat_id != allowed:
                    logger.debug("ignore telegram chat_id=%s", chat_id)
                    continue
                if not text:
                    continue
                try:
                    reply = await on_text(text)
                except Exception:  # noqa: BLE001
                    logger.exception("telegram on_text failed")
                    reply = "处理消息时出错，请稍后再试。"
                if reply:
                    await client.send_message(chat_id, reply)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            if stop_event.is_set():
                break
            logger.exception("telegram poll error; backing off")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=error_backoff_s)
            except TimeoutError:
                pass
    logger.info("Telegram poll loop stopped")
