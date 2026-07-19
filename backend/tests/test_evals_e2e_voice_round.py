"""Eval runner: evals/e2e/ws_voice_round_no_daily.json (Phase Q.5)."""

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
from fastapi.testclient import TestClient

from evals_paths import evals_path
from fae.api import create_app
from fae.llm import FakeProvider, LLMClient
from fae.tts.stub_server import app as stub_tts_app

_CASE = json.loads(
    evals_path("e2e", "ws_voice_round_no_daily.json").read_text(encoding="utf-8")
)


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


@pytest.mark.asyncio
async def test_eval_ws_voice_round_no_daily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _CASE.get("require_daily") is False
    # Browser path: must not depend on Daily credentials.
    monkeypatch.delenv("DAILY_API_KEY", raising=False)

    reply = _CASE["expect_assistant_contains"]
    fake = FakeProvider(tokens=list(reply), echo=False)
    app = create_app(llm_client=LLMClient(provider=fake))

    tokens: list[str] = []
    with _running_server(app) as url:
        async with websockets.connect(url) as ws:
            payload = {
                "type": "chat",
                "session_id": "default",
                "request": {
                    "config": {
                        "base_url": "http://x",
                        "api_key": "k",
                        "model": "m",
                    },
                    "messages": [
                        {"role": "user", "content": _CASE["user_text"]}
                    ],
                    "session_id": "default",
                },
            }
            await ws.send(json.dumps(payload))
            done = False
            for _ in range(40):
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                msg = json.loads(raw)
                if msg["type"] == "token":
                    tokens.append(msg["content"])
                elif msg["type"] == "done":
                    done = True
                    break
                elif msg["type"] == "error":
                    pytest.fail(f"ws error: {msg}")
            assert done

    text = "".join(tokens)
    assert reply in text

    # Local TTS stub (no cloud) — RIFF WAV
    tts = TestClient(stub_tts_app)
    resp = tts.post(
        "/v1/audio/speech",
        json={
            "input": _CASE["tts_text"],
            "voice": "Cherry",
            "model": "qwen3-tts",
        },
    )
    assert resp.status_code == 200
    magic = _CASE.get("expect_tts_magic") or "RIFF"
    assert resp.content[:4] == magic.encode("ascii")
