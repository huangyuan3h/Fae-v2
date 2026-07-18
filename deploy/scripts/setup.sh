#!/usr/bin/env bash
# One-time local setup for FAE-v2.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "==> FAE-v2 setup"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "    created .env from .env.example — fill in DASHSCOPE_API_KEY before voice demos"
else
  echo "    .env already present"
fi

if command -v uv >/dev/null 2>&1; then
  echo "    syncing backend deps with uv"
  (cd backend && uv sync --group dev)
else
  echo "    uv not found — skip local backend sync (Docker builds still work)"
fi

if command -v docker >/dev/null 2>&1; then
  echo "    docker available — images will build on first start.sh"
else
  echo "    WARNING: docker not found; deploy/scripts/start.sh will fail"
fi

echo "==> setup complete"
echo "    next: ./deploy/scripts/start.sh"
