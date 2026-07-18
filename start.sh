#!/usr/bin/env bash
# Local backend dev server (uv + reload).
# Full docker stack: ./deploy/scripts/start.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT/backend"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

uv sync --group dev --quiet

echo "Starting FAE-v2 backend on http://localhost:8000"
echo "(docker stack: ./deploy/scripts/start.sh)"
exec uv run uvicorn fae.api:app --reload --port 8000
