"""Integration tests for /api/chat/history and lifespan cleanup task."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
import uvicorn
import websockets
from fastapi.testclient import TestClient

from fae.api import create_app
from fae.chat_history import ChatHistoryStore
from fae.config import Settings
from fae.llm import FakeProvider, LLMClient
from fae.llm.errors import LLMError


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _running_server(app) -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"server did not start on port {port}")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=3.0)


def _close_store(app) -> None:
    store = getattr(app.state, "chat_history", None)
    if isinstance(store, ChatHistoryStore):
        store.close()
    app.state.chat_history_cleanup_task = None


def test_history_endpoint_returns_empty_when_no_turns(tmp_path: Path) -> None:
    fake = FakeProvider(tokens=["hello back"])
    settings = Settings(chat_history_db_path=str(tmp_path / "history-empty.db"))
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        client = TestClient(app)
        with client:
            resp = client.get("/api/chat/history?session_id=default")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "default"
        assert body["retention_days"] == 7
        assert body["turns"] == []
    finally:
        _close_store(app)


def test_http_chat_persists_even_without_memory(tmp_path: Path) -> None:
    fake = FakeProvider(responses=["hello back"], echo=False)
    settings = Settings(
        letta_mode="off",
        chat_history_db_path=str(tmp_path / "history-http.db"),
    )
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/chat",
                json={
                    "config": {"base_url": "http://x", "api_key": "k", "model": "m"},
                    "messages": [{"role": "user", "content": "hi"}],
                    "session_id": "default",
                },
            )
            assert resp.status_code == 200
            history = client.get("/api/chat/history?session_id=default")
        body = history.json()
        assert body["turns"][0]["user_text"] == "hi"
        assert body["turns"][0]["assistant_text"] == "hello back"
    finally:
        _close_store(app)


def test_history_endpoint_keeps_recent_turns_after_multiple_chats(
    tmp_path: Path,
) -> None:
    fake = FakeProvider(responses=["hi", "hi", "hi"], echo=False)
    settings = Settings(
        chat_history_db_path=str(tmp_path / "history-multi.db"),
    )
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        with TestClient(app) as client:
            for content in ["a", "b", "c"]:
                resp = client.post(
                    "/api/chat",
                    json={
                        "config": {"base_url": "x", "api_key": "k", "model": "m"},
                        "messages": [{"role": "user", "content": content}],
                        "session_id": "loop",
                    },
                )
                assert resp.status_code == 200
            history = client.get(
                "/api/chat/history?session_id=loop&limit=10"
            )
        body = history.json()
        assert [t["user_text"] for t in body["turns"]] == ["a", "b", "c"]
    finally:
        _close_store(app)


def test_history_endpoint_rejects_missing_session(tmp_path: Path) -> None:
    fake = FakeProvider(responses=["hi"], echo=False)
    settings = Settings(
        chat_history_db_path=str(tmp_path / "history-missing.db"),
    )
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        with TestClient(app) as client:
            resp = client.get("/api/chat/history")
        assert resp.status_code == 422
    finally:
        _close_store(app)


def test_history_endpoint_validates_retention_days_setting(tmp_path: Path) -> None:
    fake = FakeProvider(responses=["hi"], echo=False)
    settings = Settings(
        chat_history_db_path=str(tmp_path / "history-retention.db"),
        chat_history_retention_days=14,
    )
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        with TestClient(app) as client:
            history = client.get(
                "/api/chat/history?session_id=default"
            )
        body = history.json()
        assert body["retention_days"] == 14
    finally:
        _close_store(app)


def test_history_endpoint_pagination(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    fake = FakeProvider(responses=["hi"], echo=False)
    settings = Settings(chat_history_db_path=str(tmp_path / "history-page.db"))
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        store: ChatHistoryStore = app.state.chat_history
        base = datetime.now(UTC)
        store.append(
            "pg",
            "old-1",
            "old-1 reply",
            created_at=base - timedelta(minutes=10),
        )
        store.append(
            "pg",
            "old-2",
            "old-2 reply",
            created_at=base - timedelta(minutes=5),
        )
        store.append(
            "pg",
            "new",
            "new reply",
            created_at=base - timedelta(seconds=10),
        )
        with TestClient(app) as client:
            page = client.get("/api/chat/history?session_id=pg&limit=2")
            assert page.status_code == 200
            body = page.json()
            assert body["has_more"] is True
            assert [t["user_text"] for t in body["turns"]] == ["old-2", "new"]

            older = client.get(
                f"/api/chat/history?session_id=pg&limit=2"
                f"&before={body['turns'][0]['created_at']}"
            )
            assert older.status_code == 200
            older_body = older.json()
            assert older_body["has_more"] is False
            assert [t["user_text"] for t in older_body["turns"]] == ["old-1"]
    finally:
        _close_store(app)


def test_history_endpoint_rejects_invalid_before_cursor(tmp_path: Path) -> None:
    fake = FakeProvider(responses=["hi"], echo=False)
    settings = Settings(chat_history_db_path=str(tmp_path / "history-bad-cursor.db"))
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/api/chat/history?session_id=default&before=not-a-date"
            )
        assert resp.status_code == 400
    finally:
        _close_store(app)


def test_sessions_endpoint_lists_active_buckets(tmp_path: Path) -> None:
    fake = FakeProvider(responses=["hi"], echo=False)
    settings = Settings(chat_history_db_path=str(tmp_path / "history-sess-list.db"))
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        store: ChatHistoryStore = app.state.chat_history
        store.append("alpha", "a", "A")
        store.append("beta", "b", "B")
        store.append("beta", "b2", "B2")
        with TestClient(app) as client:
            resp = client.get("/api/chat/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["retention_days"] == 7
        ids = [s["session_id"] for s in body["sessions"]]
        assert "alpha" in ids and "beta" in ids
        beta = next(s for s in body["sessions"] if s["session_id"] == "beta")
        assert beta["turn_count"] == 2
        assert beta["title"] == "b"
        assert beta["pinned"] is False
    finally:
        _close_store(app)


def test_patch_session_title_endpoint(tmp_path: Path) -> None:
    fake = FakeProvider(responses=["hi"], echo=False)
    settings = Settings(chat_history_db_path=str(tmp_path / "history-patch.db"))
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        store: ChatHistoryStore = app.state.chat_history
        store.append("edit", "原始标题", "ok")
        with TestClient(app) as client:
            resp = client.patch(
                "/api/chat/sessions/edit",
                json={"title": "新标题"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["title"] == "新标题"
            missing = client.patch(
                "/api/chat/sessions/missing-id",
                json={"title": "x"},
            )
            assert missing.status_code == 404
    finally:
        _close_store(app)


def test_pin_endpoint_toggles_flag(tmp_path: Path) -> None:
    fake = FakeProvider(responses=["hi"], echo=False)
    settings = Settings(chat_history_db_path=str(tmp_path / "history-pin-api.db"))
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        store: ChatHistoryStore = app.state.chat_history
        store.append("p", "hi", "hello")
        with TestClient(app) as client:
            resp = client.post(
                "/api/chat/sessions/p/pin", json={"pinned": True},
            )
            assert resp.status_code == 200
            assert resp.json()["pinned"] is True
            resp = client.post(
                "/api/chat/sessions/p/pin", json={"pinned": False},
            )
            assert resp.status_code == 200
            assert resp.json()["pinned"] is False
    finally:
        _close_store(app)


def test_lifespan_cleanup_task_starts_and_shuts_down(tmp_path: Path) -> None:
    fake = FakeProvider(responses=["hi"], echo=False)
    settings = Settings(
        chat_history_db_path=str(tmp_path / "history-lifespan.db"),
        chat_history_cleanup_interval_s=0.05,
    )
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    with TestClient(app) as client:
        assert app.state.chat_history_cleanup_task is not None
        assert not app.state.chat_history_cleanup_task.done()
        assert client.get("/health").status_code == 200
    assert app.state.chat_history is None
    assert app.state.chat_history_cleanup_task is None


async def test_ws_chat_persists_turn(tmp_path: Path) -> None:
    fake = FakeProvider(tokens=["你", "好"])
    settings = Settings(
        chat_history_db_path=str(tmp_path / "history-ws.db"),
        chat_history_cleanup_interval_s=3600.0,
    )
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))

    with _running_server(app) as base:
        ws_url = f"{base.replace('http', 'ws')}/ws/chat"
        async with websockets.connect(ws_url) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "chat",
                        "session_id": "ws-session",
                        "request": {
                            "config": {
                                "base_url": "http://x",
                                "api_key": "k",
                                "model": "m",
                            },
                            "messages": [{"role": "user", "content": "hi"}],
                            "session_id": "ws-session",
                        },
                    }
                )
            )
            for _ in range(20):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg["type"] == "done":
                    break
                if msg["type"] == "error":
                    pytest.fail(f"ws error frame: {msg}")

    try:
        with TestClient(app) as client:
            history = client.get(
                "/api/chat/history?session_id=ws-session&limit=10"
            )
        body = history.json()
        assert [t["user_text"] for t in body["turns"]] == ["hi"]
        assert body["turns"][0]["assistant_text"] == "你好"
    finally:
        _close_store(app)


def test_history_endpoint_surfaces_llm_errors(tmp_path: Path) -> None:
    err = LLMError(code="timeout", message="slow")
    fake = FakeProvider(error=err)
    settings = Settings(
        chat_history_db_path=str(tmp_path / "history-err.db"),
    )
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/chat",
                json={
                    "config": {"base_url": "x", "api_key": "k", "model": "m"},
                    "messages": [{"role": "user", "content": "hi"}],
                    "session_id": "err",
                },
            )
            assert resp.status_code == 504
            history = client.get(
                "/api/chat/history?session_id=err&limit=10"
            )
        assert history.json()["turns"] == []
    finally:
        _close_store(app)
