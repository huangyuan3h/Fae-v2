"""Integration tests for the /ws/chat WebSocket endpoint.

Starlette's TestClient.websocket_connect doesn't play well with
pytest-asyncio's auto mode (the anyio portal conflicts with how
the test runner drives the event loop), so we spin up a real
uvicorn server on an ephemeral port and talk to it via the
`websockets` client library.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from typing import Iterator

import pytest
import uvicorn
import websockets

from fae.api import create_app
from fae.llm import FakeProvider, LLMClient
from fae.llm.errors import LLMError


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _running_server(app) -> Iterator[str]:
    """Yield the ws:// URL for a uvicorn server running `app`."""
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

    # Poll until the server starts accepting.
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


# ── Tests ─────────────────────────────────────────────────────────────


async def test_ws_chat_streams_tokens() -> None:
    fake = FakeProvider(tokens=["你", "好", "，", "世界"])
    app = create_app(llm_client=LLMClient(provider=fake))

    with _running_server(app) as url:
        async with websockets.connect(url) as ws:
            await ws.send(
                '{"type":"chat","request":{'
                '"config":{"base_url":"http://x","api_key":"k","model":"m"},'
                '"messages":[{"role":"user","content":"hi"}]}}'
            )
            tokens: list[str] = []
            done_seen = False
            for _ in range(20):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg["type"] == "token":
                    tokens.append(msg["content"])
                elif msg["type"] == "done":
                    done_seen = True
                    break
                elif msg["type"] == "error":
                    pytest.fail(f"unexpected error frame: {msg}")
            assert done_seen
            assert "".join(tokens) == "你好，世界"


async def test_ws_chat_sends_error_on_llm_error() -> None:
    err = LLMError(code="auth", message="bad key")
    fake = FakeProvider(tokens=["a"], error=err)
    app = create_app(llm_client=LLMClient(provider=fake))

    with _running_server(app) as url:
        async with websockets.connect(url) as ws:
            await ws.send(
                '{"type":"chat","request":{'
                '"config":{"base_url":"http://x","api_key":"k","model":"m"},'
                '"messages":[{"role":"user","content":"hi"}]}}'
            )
            for _ in range(10):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg["type"] == "error":
                    assert msg["code"] == "auth"
                    assert "bad key" in msg["message"]
                    return
            pytest.fail("did not receive error frame")


async def test_ws_chat_validates_request_payload() -> None:
    """A bad ChatRequest must yield an error frame, not a crash."""
    fake = FakeProvider(tokens=["ok"])
    app = create_app(llm_client=LLMClient(provider=fake))

    with _running_server(app) as url:
        async with websockets.connect(url) as ws:
            # Missing required `messages` field.
            await ws.send(
                '{"type":"chat","request":{'
                '"config":{"base_url":"http://x","api_key":"k","model":"m"}}}'
            )
            for _ in range(5):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg["type"] == "error":
                    assert msg["code"] == "bad_request"
                    return
            pytest.fail("did not receive validation error frame")


async def test_ws_chat_rejects_unknown_message_type() -> None:
    fake = FakeProvider()
    app = create_app(llm_client=LLMClient(provider=fake))

    with _running_server(app) as url:
        async with websockets.connect(url) as ws:
            await ws.send('{"type":"bogus"}')
            for _ in range(5):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg["type"] == "error":
                    assert "bogus" in msg["message"]
                    return
            pytest.fail("did not receive unknown-type error")


async def test_ws_chat_cancel_stops_stream() -> None:
    """A `cancel` message aborts the in-flight stream without crashing."""
    fake = FakeProvider(tokens=[c for c in "abcdefghijklmnop"], echo=False)
    app = create_app(llm_client=LLMClient(provider=fake))

    with _running_server(app) as url:
        async with websockets.connect(url) as ws:
            await ws.send(
                '{"type":"chat","request":{'
                '"config":{"base_url":"http://x","api_key":"k","model":"m"},'
                '"messages":[{"role":"user","content":"hi"}]}}'
            )
            for _ in range(2):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                json.loads(raw)  # ignore content
            await ws.send('{"type":"cancel"}')
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except (asyncio.TimeoutError, websockets.ConnectionClosed):
                    return
                msg = json.loads(raw)
                if msg["type"] == "done":
                    return
            pytest.fail("did not receive done after cancel")


async def test_ws_chat_emits_turn_started_and_done_turn_id() -> None:
    """`turn_started` fires before any tokens; `done` carries ``turn_id``
    and ``chat_turn_id`` so the FE can join the trace to a chat turn."""
    fake = FakeProvider(tokens=["你", "好"], echo=False)
    app = create_app(llm_client=LLMClient(provider=fake))

    with _running_server(app) as url:
        async with websockets.connect(url) as ws:
            await ws.send(
                '{"type":"chat","request":{'
                '"config":{"base_url":"http://x","api_key":"k","model":"m"},'
                '"messages":[{"role":"user","content":"hi"}],'
                '"session_id":"ws-turn"}}'
            )
            turn_started_id: str | None = None
            done_payload: dict | None = None
            for _ in range(20):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg["type"] == "turn_started":
                    turn_started_id = msg["turn_id"]
                elif msg["type"] == "done":
                    done_payload = msg
                    break
            assert turn_started_id
            assert done_payload is not None
            assert done_payload["turn_id"] == turn_started_id
            assert done_payload["chat_turn_id"]  # uuid string
