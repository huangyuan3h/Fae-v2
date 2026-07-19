#!/usr/bin/env bash
# Start the slim always-on Agent Core (embedded memory, no full stack).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill the Always-on Core block"
  echo "  cp .env.example .env"
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

COMPOSE_FILE=( -f docker-compose.core.yml )
PROFILE_ARGS=()
OVERRIDE=""

if [[ "${WITH_TTS_STUB:-}" == "1" ]]; then
  PROFILE_ARGS=( --profile tts )
  OVERRIDE="$REPO_ROOT/.compose-core-tts.override.yml"
  cat >"$OVERRIDE" <<'YAML'
services:
  backend:
    environment:
      VLLM_TTS_URL: http://tts:8880/v1
    depends_on:
      - tts
YAML
  COMPOSE_FILE+=( -f "$OVERRIDE" )
fi

echo "==> Building and starting FAE Core (slim)"
"${COMPOSE[@]}" "${COMPOSE_FILE[@]}" "${PROFILE_ARGS[@]}" up -d --build

echo "==> Waiting for /ready"
ok=0
for _ in $(seq 1 60); do
  code="$(curl -s -o /tmp/fae-ready.json -w '%{http_code}' http://127.0.0.1:8000/ready 2>/dev/null || echo 000)"
  body="$(cat /tmp/fae-ready.json 2>/dev/null || true)"
  if [[ "$code" == "200" || "$code" == "503" ]] && [[ -n "$body" ]]; then
    echo "    HTTP $code $body"
    if echo "$body" | grep -q '"memory"[[:space:]]*:[[:space:]]*"down"'; then
      sleep 2
      continue
    fi
    if [[ "$code" == "200" ]]; then
      ok=1
      break
    fi
  fi
  sleep 2
done

if [[ "$ok" -ne 1 ]]; then
  echo "Backend did not become ready in time. Check:"
  echo "  ${COMPOSE[*]} -f docker-compose.core.yml logs backend"
  exit 1
fi

echo ""
echo "Core:    http://127.0.0.1:8000"
echo "Ready:   http://127.0.0.1:8000/ready"
echo "Docs:    http://127.0.0.1:8000/docs"
echo "Deploy:  doc/DEPLOY.md"
echo ""
echo "Telegram/Loop use server DASHSCOPE_API_KEY or PROACTIVE_LLM_* (no browser Key)."

if [[ -n "$OVERRIDE" ]]; then
  echo "Note: TTS stub override at $OVERRIDE (gitignored if listed)."
fi
