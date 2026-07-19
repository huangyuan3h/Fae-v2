"""Phase 5.1 — Telegram channel bridge + outbound (mocked, no network)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fae.channels.bridge import (
    NO_LLM_REPLY,
    handle_inbound_text,
    resolve_server_llm_config,
)
from fae.channels.telegram import (
    TelegramClient,
    _extract_text,
    telegram_poll_loop,
    telegram_ready,
)
from fae.config import Settings, get_settings
from fae.llm import LLMClient
from fae.llm.provider import FakeProvider
from fae.scheduler.delivery import NotificationDelivery
from fae.scheduler.hub import ConnectionHub
from fae.scheduler.store import ScheduleStore
from memory_helpers import make_embedded


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_telegram_ready_requires_token_and_chat_id() -> None:
    assert not telegram_ready(
        Settings(telegram_bot_token="", telegram_chat_id="1")
    )
    assert not telegram_ready(
        Settings(telegram_bot_token="tok", telegram_chat_id="")
    )
    assert not telegram_ready(
        Settings(
            telegram_enabled=False,
            telegram_bot_token="tok",
            telegram_chat_id="1",
        )
    )
    assert telegram_ready(
        Settings(telegram_bot_token="tok", telegram_chat_id="99")
    )


def test_resolve_server_llm_config_none_without_key() -> None:
    assert resolve_server_llm_config(Settings(dashscope_api_key="")) is None
    cfg = resolve_server_llm_config(
        Settings(dashscope_api_key="sk-test", proactive_llm_model="qwen-plus")
    )
    assert cfg is not None
    assert cfg.api_key == "sk-test"
    assert cfg.model == "qwen-plus"


def test_extract_text_from_update() -> None:
    chat_id, text = _extract_text(
        {
            "update_id": 1,
            "message": {"chat": {"id": 42}, "text": "  hello  "},
        }
    )
    assert chat_id == "42"
    assert text == "hello"
    chat_id, text = _extract_text({"update_id": 2, "message": {"chat": {"id": 1}}})
    assert chat_id == "1"
    assert text is None


@pytest.mark.asyncio
async def test_handle_inbound_no_llm_key() -> None:
    settings = Settings(dashscope_api_key="", proactive_llm_api_key="")
    reply = await handle_inbound_text(
        "hi",
        settings=settings,
        llm=LLMClient(provider=FakeProvider(responses=["x"])),
    )
    assert reply == NO_LLM_REPLY


@pytest.mark.asyncio
async def test_handle_inbound_fake_llm_and_persist(tmp_path: Path) -> None:
    client, _recall, service = make_embedded(tmp_path, name="tg-mem.db")
    await client.ensure_agent()
    settings = Settings(
        dashscope_api_key="sk-test",
        letta_mode="embedded",
        scheduler_enabled=False,
    )
    reply = await handle_inbound_text(
        "我叫小明，住在上海",
        settings=settings,
        llm=LLMClient(provider=FakeProvider(responses=["记住了"], echo=False)),
        memory=service,
        session_id="default",
    )
    assert "记住" in reply or reply == "记住了"
    prompt = await client.recall_for_prompt("我叫什么", session_id="default")
    assert "小明" in prompt or "上海" in prompt
    await client.close()


@pytest.mark.asyncio
async def test_telegram_send_and_get_updates_mocked() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path.endswith("/sendMessage"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        if path.endswith("/getUpdates"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        {
                            "update_id": 10,
                            "message": {
                                "chat": {"id": 7},
                                "text": "ping",
                            },
                        }
                    ],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    bot = TelegramClient("test-token", http=http, api_base="https://tg.test")
    assert await bot.send_message("7", "hello")
    updates = await bot.get_updates(timeout=1)
    assert len(updates) == 1
    assert updates[0]["update_id"] == 10
    await bot.close()
    await http.aclose()


@pytest.mark.asyncio
async def test_telegram_poll_loop_replies_bound_chat() -> None:
    sent: list[tuple[str, str]] = []
    updates_left = [
        {
            "update_id": 1,
            "message": {"chat": {"id": 99}, "text": "ignore other"},
        },
        {
            "update_id": 2,
            "message": {"chat": {"id": 7}, "text": "hi"},
        },
    ]

    class _FakeBot:
        async def get_updates(self, offset=None, *, timeout=25):
            if updates_left:
                return [updates_left.pop(0)]
            return []

        async def send_message(self, chat_id: str, text: str) -> bool:
            sent.append((chat_id, text))
            return True

    stop = asyncio.Event()

    async def on_text(text: str) -> str:
        stop.set()
        return f"echo:{text}"

    await telegram_poll_loop(
        _FakeBot(),  # type: ignore[arg-type]
        allowed_chat_id="7",
        on_text=on_text,
        stop_event=stop,
        long_poll_timeout=0,
        error_backoff_s=0.01,
    )
    assert sent == [("7", "echo:hi")]


@pytest.mark.asyncio
async def test_delivery_calls_telegram_sender(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "sched.db")
    hub = ConnectionHub()
    seen: list[str] = []

    async def sender(text: str) -> bool:
        seen.append(text)
        return True

    delivery = NotificationDelivery(store, hub, telegram_sender=sender)
    item = await delivery.notify("提醒", "喝水", session_id="default")
    assert item.id
    assert any("喝水" in t for t in seen)
    store.close()


def test_lifespan_skips_telegram_without_token() -> None:
    from fae.api import create_app
    from fastapi.testclient import TestClient

    settings = Settings(
        telegram_bot_token="",
        telegram_chat_id="",
        scheduler_enabled=False,
        letta_mode="off",
    )
    app = create_app(
        settings=settings,
        llm_client=LLMClient(provider=FakeProvider()),
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert getattr(client.app.state, "telegram_task", None) is None


@pytest.mark.asyncio
async def test_delivery_skips_telegram_when_quiet(tmp_path: Path) -> None:
    from fae.scheduler.store import NotificationPrefs

    store = ScheduleStore(tmp_path / "sched-q.db")
    store.set_prefs(
        NotificationPrefs(
            enabled=True,
            quiet_start_hour=0,
            quiet_end_hour=23,
            desktop_enabled=False,
            web_push_enabled=False,
        )
    )
    seen: list[str] = []

    async def sender(text: str) -> bool:
        seen.append(text)
        return True

    delivery = NotificationDelivery(
        store, ConnectionHub(), telegram_sender=sender
    )
    # Quiet for hours 0..22; force now into quiet with monkeypatch.
    import fae.scheduler.delivery as del_mod

    original = del_mod.in_quiet_hours
    del_mod.in_quiet_hours = lambda *a, **k: True  # type: ignore[assignment]
    try:
        await delivery.notify("t", "b")
        assert seen == []
    finally:
        del_mod.in_quiet_hours = original
        store.close()


def test_telegram_client_requires_token() -> None:
    with pytest.raises(ValueError):
        TelegramClient("")


@pytest.mark.asyncio
async def test_telegram_send_truncates_and_handles_errors() -> None:
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sendMessage"):
            body = json.loads(request.content.decode())
            assert len(body["text"]) <= 4000
            return httpx.Response(400, json={"ok": False, "description": "bad"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    bot = TelegramClient("tok", http=http, api_base="https://tg.test")
    assert not await bot.send_message("1", "x" * 5000)
    assert not await bot.send_message("1", "")
    await http.aclose()


@pytest.mark.asyncio
async def test_telegram_get_updates_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "result": []})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    bot = TelegramClient("tok", http=http, api_base="https://tg.test")
    assert await bot.get_updates() == []
    await http.aclose()


@pytest.mark.asyncio
async def test_telegram_poll_empty_chat_id_and_on_text_error() -> None:
    stop = asyncio.Event()
    stop.set()
    await telegram_poll_loop(
        object(),  # type: ignore[arg-type]
        allowed_chat_id="",
        on_text=lambda t: asyncio.sleep(0, result="x"),  # type: ignore[arg-type,return-value]
        stop_event=stop,
    )

    class _Bot:
        def __init__(self) -> None:
            self.n = 0

        async def get_updates(self, offset=None, *, timeout=25):
            self.n += 1
            if self.n == 1:
                return [
                    {
                        "update_id": 1,
                        "message": {"chat": {"id": 7}, "text": "boom"},
                    }
                ]
            return []

        async def send_message(self, chat_id: str, text: str) -> bool:
            assert "出错" in text
            return True

    stop2 = asyncio.Event()

    async def bad_on_text(text: str) -> str:
        stop2.set()
        raise RuntimeError("fail")

    await telegram_poll_loop(
        _Bot(),  # type: ignore[arg-type]
        allowed_chat_id="7",
        on_text=bad_on_text,
        stop_event=stop2,
        long_poll_timeout=0,
        error_backoff_s=0.01,
    )


@pytest.mark.asyncio
async def test_bridge_handle_inbound_success() -> None:
    settings = Settings(
        dashscope_api_key="sk-test",
        scheduler_enabled=False,
        subagent_enabled=True,
    )
    reply = await handle_inbound_text(
        "hello",
        settings=settings,
        llm=LLMClient(provider=FakeProvider(responses=["hi there"], echo=False)),
    )
    assert "hi" in reply.lower() or reply == "hi there"
