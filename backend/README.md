# FAE-v2 Backend

Python backend for FAE-v2: FastAPI HTTP + (later) Pipecat voice pipeline.

## Layout

```
backend/
├── pyproject.toml          # uv-managed Python project
├── uv.lock                 # resolved dependency graph
├── .python-version         # 3.12
├── src/fae/
│   ├── __init__.py
│   ├── config.py           # pydantic-settings env loader
│   └── api.py              # FastAPI app (health/ready endpoints)
└── tests/
    ├── test_api.py         # endpoint + lifespan tests
    └── test_config.py      # env loading + defaults + cache
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

## Endpoints (Checkpoint 1)

| Method | Path     | Description                              |
|--------|----------|------------------------------------------|
| GET    | /health  | Liveness probe (always 200 if process up) |
| GET    | /ready   | Readiness probe (checks config loaded)     |
| GET    | /docs    | Auto-generated OpenAPI / Swagger UI        |
