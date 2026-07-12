#!/usr/bin/env bash
# Start the FAE-v2 backend in dev mode.
# Checkpoint 1: backend only. UI lands in a later checkpoint.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT/backend"

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

# Sync deps on every start (fast when cache is warm).
uv sync --extra dev --quiet

echo "🚀 Starting FAE-v2 backend on http://localhost:8000"
exec uv run uvicorn fae.api:app --reload --port 8000
