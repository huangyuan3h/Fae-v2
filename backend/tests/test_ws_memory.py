"""WS chat with embedded memory — recall inject + persist_turn."""

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

from fae.api import create_app
from fae.config import Settings
from fae.llm import FakeProvider, LLMClient


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

    def _serve() -> None:
        asyncio.run(server.serve())

    thread = threading.Thread(target=_serve, daemon=True)
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
        yield f"ws://127.0.0.1:{port}/ws/chat"
    finally:
        server.should_exit = True
        thread.join(timeout=3.0)


async def _chat_until_done(
    ws: websockets.ClientConnection,
    content: str,
    *,
    session_id: str = "sess-m22",
) -> None:
    await ws.send(
        json.dumps(
            {
                "type": "chat",
                "session_id": session_id,
                "request": {
                    "config": {
                        "base_url": "http://x",
                        "api_key": "k",
                        "model": "m",
                    },
                    "messages": [{"role": "user", "content": content}],
                    "session_id": session_id,
                },
            }
        )
    )
    for _ in range(30):
        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
        msg = json.loads(raw)
        if msg["type"] == "done":
            assert msg.get("session_id") == session_id
            return
        if msg["type"] == "error":
            pytest.fail(f"error frame: {msg}")


async def test_ws_persists_name_and_injects_on_next_turn(tmp_path: Path) -> None:
    fake = FakeProvider(tokens=["好", "的"])
    settings = Settings(
        letta_mode="embedded",
        letta_embedded_path=str(tmp_path / "ws-mem.db"),
        recall_db_path=str(tmp_path / "ws-mem-recall.db"),
        archival_prefer_stub=True,
    )
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))

    with _running_server(app) as url:
        async with websockets.connect(url) as ws:
            await _chat_until_done(ws, "我叫小明")
            await _chat_until_done(ws, "我叫什么")

    assert len(fake.stream_calls) >= 2
    second = fake.stream_calls[1]
    assert second.messages[0].role == "system"
    assert "<fae_memory>" in second.messages[0].content
    assert "小明" in second.messages[0].content


async def test_ws_multi_topic_recall_includes_prior_topic(tmp_path: Path) -> None:
    fake = FakeProvider(tokens=["嗯"])
    settings = Settings(
        letta_mode="embedded",
        letta_embedded_path=str(tmp_path / "ws-m22.db"),
        recall_db_path=str(tmp_path / "ws-m22-recall.db"),
        archival_prefer_stub=True,
    )
    app = create_app(settings=settings, llm_client=LLMClient(provider=fake))
    sid = "multi-topic"

    with _running_server(app) as url:
        async with websockets.connect(url) as ws:
            await _chat_until_done(ws, "我在做一个 Python 项目", session_id=sid)
            await _chat_until_done(ws, "周末想去爬山", session_id=sid)
            await _chat_until_done(
                ws, "刚才提到的 Python 那个项目怎么样", session_id=sid
            )

    assert len(fake.stream_calls) >= 3
    last = fake.stream_calls[-1]
    assert last.messages[0].role == "system"
    assert "Python" in last.messages[0].content
    assert "[recent_turns]" in last.messages[0].content
