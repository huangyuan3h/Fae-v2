# FAE-v2 Backend

Python backend for FAE-v2: FastAPI HTTP + (later) Pipecat voice pipeline.

## Layout

```
backend/
├── pyproject.toml          # uv-managed Python project
├── .python-version         # 3.12
├── src/fae/
│   ├── __init__.py
│   ├── config.py           # pydantic-settings env loader
│   └── api.py              # FastAPI app (health/ready endpoints)
└── tests/
    └── test_health.py
```

## Development

```bash
# 1. Install uv (if not already)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Sync dependencies (creates .venv automatically)
cd backend
uv sync --extra dev

# 3. Run tests
uv run pytest

# 4. Start dev server
uv run uvicorn fae.api:app --reload --port 8000

# 5. Verify
curl http://localhost:8000/health
# → {"status":"ok"}
```

## Endpoints (Checkpoint 1)

| Method | Path     | Description                              |
|--------|----------|------------------------------------------|
| GET    | /health  | Liveness probe (always 200 if process up) |
| GET    | /ready   | Readiness probe (checks config loaded)     |
