# FAE-v2 Backend

Python backend for FAE-v2: FastAPI (`/ws/chat`, memory, skills, scheduler, local TTS) plus optional Daily/Pipecat voice.

**Canonical docs**: [../README.md](../README.md) · [../doc/ARCHITECTURE.md](../doc/ARCHITECTURE.md) · [../doc/DEVELOPMENT_PLAN.md](../doc/DEVELOPMENT_PLAN.md)

**Default voice path**: browser STT → `/ws/chat` → local TTS (`VLLM_TTS_URL`). Daily is optional. LiveKit / MCP are not in scope.

**Telegram (optional)**: set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — long polling via `fae/channels/`; inbound uses the same agent bridge as `/api/chat`; outbound hooks `NotificationDelivery`.

**Subagents (Phase 5.2)**: tool `run_subagent` in `fae/agent/subagents/` (researcher / coder / reviewer); summaries upsert to archival; WS emits `subagent` start/done events.

**Evals**: case data in [`../evals/`](../evals/); runners are `tests/test_evals_*.py` (picked up by `uv run pytest`).

## Layout

```
backend/
├── pyproject.toml          # uv-managed Python project
├── uv.lock                 # resolved dependency graph
├── .python-version         # 3.12
├── src/fae/
│   ├── __init__.py
│   ├── config.py           # pydantic-settings env loader
│   ├── api/                # FastAPI app package
│   │   ├── __init__.py     #   create_app() + HTTP endpoints (app.state DI)
│   │   ├── deps.py         #   shared get_llm_client (HTTP + WS)
│   │   └── ws.py           #   /ws/chat WebSocket streaming
│   └── llm/                # LLM abstraction layer
│       ├── errors.py       #   normalised LLMError (code + message)
│       ├── types.py        #   LLMConfig, ChatMessage, ChatRequest, ChatResponse
│       ├── provider.py     #   AsyncOpenAI chat/stream + FakeProvider
│       └── client.py       #   LLMClient wrapper (chat, stream, test_connection)
└── tests/
    ├── test_api.py
    ├── test_config.py
    ├── test_chat_endpoints.py
    ├── test_llm_client.py
    ├── test_llm_provider.py
    ├── test_llm_types.py
    └── test_ws_chat.py
```

## Development

```bash
# 1. Install uv (if not already)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Sync dependencies (creates .venv automatically)
cd backend
uv sync --extra dev

# 3. Run tests (with coverage gate enforced)
uv run pytest
# → 10 passed, Total coverage: 100.00%

# 4. Start dev server
uv run uvicorn fae.api:app --reload --port 8000

# 5. Verify
curl http://localhost:8000/health
# → {"status":"ok"}
```

## Testing & coverage

Tests are run with `pytest`. Coverage is enforced via `pytest-cov` and
fails the run if total line+branch coverage drops below **80%**.

```bash
# Default: terminal report + HTML report in htmlcov/
uv run pytest

# Terminal-only report, no HTML
uv run pytest --no-cov-on-fail --no-cov --cov=src/fae --cov-report=term

# Open the HTML report
open htmlcov/index.html

# Run only fast unit tests (skip integration-tagged ones, once added)
uv run pytest -m "not integration"
```

### Coverage policy

| Setting | Value | Why |
|---|---|---|
| Source scope | `src/fae` | Measure OUR code, not transitive deps |
| Branch coverage | enabled | Catches untested `if/else` arms |
| Fail-under | **80%** | Application-code floor; balances quality vs velocity |
| HTML report | `htmlcov/` | Local browsing, not committed |
| Exclude | `pragma: no cover`, `NotImplementedError`, `TYPE_CHECKING` | Standard exemptions for stubs |

The 80% floor is a **floor**, not a target. As the codebase grows, the
test-to-code ratio should improve; if a PR lands and coverage drops
below 80%, the test run fails until more tests are added.

## Endpoints

| Method | Path                  | Description                                |
|--------|-----------------------|--------------------------------------------|
| GET    | /health               | Liveness probe                             |
| GET    | /ready                | Readiness: memory/scheduler/telegram/proactive_llm |
| POST   | /api/test-connection  | Probe an LLM provider (1-token, temp=0)    |
| POST   | /api/chat             | Synchronous text-only chat completion      |
| WS     | /ws/chat              | Streaming chat over WebSocket (Checkpoint 3) |
| POST   | /api/sessions         | Create in-memory session                     |
| GET    | /api/sessions         | List sessions                                |
| POST   | /api/pipeline/text    | Phase 1.3 text pipeline smoke                |
| GET    | /docs                 | Auto-generated OpenAPI / Swagger UI        |

### WebSocket protocol (`/ws/chat`)

JSON-over-text frames. One active generation per connection.

```
client -> server:
  {"type": "chat",  "request": ChatRequest}
  {"type": "cancel"}

server -> client:
  {"type": "token", "content": "你"}
  {"type": "done",  "usage": {...} | null}
  {"type": "error", "code": "auth", "message": "..."}
```

```python
import websockets, asyncio, json

async def main():
    async with websockets.connect("ws://localhost:8000/ws/chat") as ws:
        await ws.send(json.dumps({
            "type": "chat",
            "request": {
                "config": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode",
                           "api_key": "sk-xxx", "model": "qwen3-max"},
                "messages": [{"role": "user", "content": "你好"}],
            },
        }))
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "token":
                print(msg["content"], end="", flush=True)
            elif msg["type"] == "done":
                break
            elif msg["type"] == "error":
                raise RuntimeError(f"{msg['code']}: {msg['message']}")

asyncio.run(main())
```

### LLM error → HTTP status mapping

| `LLMError.code` | HTTP status | Meaning                          |
|-----------------|-------------|----------------------------------|
| `auth`          | 401         | API key invalid / missing        |
| `forbidden`     | 403         | Key valid, model not authorised  |
| `not_found`     | 404         | Model name unknown               |
| `bad_request`   | 400         | Provider rejected the request    |
| `rate_limited`  | 429         | Provider 429'd us                |
| `timeout`       | 504         | Request timed out (default 10s)  |
| `connection`    | 502         | Cannot reach the endpoint        |
| `length`        | 502         | LLM hit `max_tokens`             |
| `empty_response`| 502         | LLM returned 0 choices           |
| `unknown`       | 500         | Anything else (likely a bug)     |

### Trying the LLM endpoints with curl

```bash
# 1. Start the server
uv run uvicorn fae.api:app --port 8000

# 2. Test connection (probe a real Qwen endpoint)
curl -X POST http://localhost:8000/api/test-connection \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode",
    "api_key": "sk-your-key",
    "model": "qwen3-max"
  }'

# 3. Chat
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode",
      "api_key": "sk-your-key",
      "model": "qwen3-max"
    },
    "messages": [{"role": "user", "content": "用一句话介绍你自己"}]
  }'
```

The backend **never** persists the API key. Each request must include the
`config` block; the UI stores it in `localStorage` and re-sends on every call.
