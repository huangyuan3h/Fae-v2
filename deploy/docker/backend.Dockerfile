# Multi-stage backend image (uv → slim runtime).
# Build context: repository root.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 fae \
    && mkdir -p /app/.data \
    && chown -R fae:fae /app/.data

COPY --from=builder /app/.venv /app/.venv
COPY backend/src /app/src
COPY deploy/docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh
RUN chmod +x /usr/local/bin/backend-entrypoint.sh

# Entrypoint runs as root to chown the named volume, then drops to fae.
USER root
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

ENTRYPOINT ["/usr/local/bin/backend-entrypoint.sh"]
CMD ["uvicorn", "fae.api:app", "--host", "0.0.0.0", "--port", "8000"]
