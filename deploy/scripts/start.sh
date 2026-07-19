#!/usr/bin/env bash
# Start the full local stack via docker compose.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — run ./deploy/scripts/setup.sh first"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found"
  exit 1
fi

COMPOSE=(docker compose)
if ! docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
fi

echo "==> Building and starting FAE-v2 services"
"${COMPOSE[@]}" up -d --build

echo "==> Waiting for backend health"
for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "    backend healthy"
    break
  fi
  sleep 2
done

echo "==> Service status"
"${COMPOSE[@]}" ps

echo ""
echo "UI:      http://localhost:3000"
echo "Backend: http://localhost:8000/health"
echo "Docs:    http://localhost:8000/docs"
