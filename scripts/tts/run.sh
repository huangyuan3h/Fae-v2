#!/usr/bin/env bash
# Start OpenAI-compatible Qwen3-TTS on :8880 for npm run dev.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEP_DIR="${FAE_TTS_DIR:-$ROOT/.deps/qwen3-tts}"
READY="$ROOT/.deps/qwen3-tts.ready"
PORT="${PORT:-${FAE_TTS_PORT:-8880}}"
HOST="${HOST:-127.0.0.1}"

tts_models_ok() {
  curl -sf --max-time 2 "http://${HOST}:${PORT}/v1/models" 2>/dev/null \
    | grep -q '"object"[[:space:]]*:[[:space:]]*"list"'
}

free_stale_listener() {
  local pids pid args
  pids="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "$pids" ]] && return 0
  for pid in $pids; do
    args="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    if echo "$args" | grep -qE 'api\.main|qwen3-tts|Qwen3-TTS'; then
      echo "[fae-tts] freeing stale TTS pid=$pid on :${PORT}"
      kill "$pid" 2>/dev/null || true
    else
      echo "[fae-tts] ERROR: :${PORT} held by unrelated process pid=$pid"
      echo "[fae-tts]   $args"
      echo "[fae-tts] stop it, or set FAE_TTS_PORT / PORT to another port"
      exit 1
    fi
  done
  sleep 1
}

detect_mps() {
  # shellcheck disable=SC1091
  source "$DEP_DIR/.venv/bin/activate"
  python - <<'PY'
import sys
try:
    import torch
    sys.exit(0 if torch.backends.mps.is_available() else 1)
except Exception:
    sys.exit(1)
PY
}

if [[ ! -f "$READY" || ! -x "$DEP_DIR/.venv/bin/python" ]]; then
  echo "[fae-tts] server not installed yet — running setup (first time may take a while) ..."
  bash "$ROOT/scripts/tts/setup.sh"
fi

# Already healthy from a previous session → keep this npm slot alive (do not re-bind).
if tts_models_ok; then
  echo "[fae-tts] already healthy on http://${HOST}:${PORT} — reusing (Ctrl+C stops npm run dev only)"
  while tts_models_ok; do
    sleep 30
  done

  echo "[fae-tts] upstream gone — will start a new server"
fi

if ! tts_models_ok; then
  free_stale_listener
fi

# shellcheck disable=SC1091
source "$DEP_DIR/.venv/bin/activate"
cd "$DEP_DIR"

export HOST
export PORT
export WORKERS="${WORKERS:-1}"
export TTS_LAZY_LOAD="${TTS_LAZY_LOAD:-true}"
export TTS_MAX_CONCURRENT="${TTS_MAX_CONCURRENT:-1}"
export CORS_ORIGINS="${CORS_ORIGINS:-*}"
export TTS_MODEL_NAME="${TTS_MODEL_NAME:-Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice}"

OS="$(uname -s)"
if [[ "$OS" == "Darwin" ]]; then
  # official backend ignores MPS (cuda-or-cpu only). Use pytorch backend + mps.
  if [[ -z "${TTS_BACKEND:-}" ]]; then
    # float16 on MPS often yields NaN logits with Qwen3-TTS; use float32.
    if detect_mps; then
      export TTS_BACKEND="${TTS_BACKEND:-pytorch}"
      export TTS_DEVICE="${TTS_DEVICE:-mps}"
      export TTS_DTYPE="${TTS_DTYPE:-float32}"
      export TTS_ATTN="${TTS_ATTN:-sdpa}"
    else
      export TTS_BACKEND="${TTS_BACKEND:-pytorch}"
      export TTS_DEVICE="${TTS_DEVICE:-cpu}"
      export TTS_DTYPE="${TTS_DTYPE:-float32}"
      export TTS_ATTN="${TTS_ATTN:-sdpa}"
    fi
  fi
  echo "[fae-tts] darwin backend=${TTS_BACKEND} device=${TTS_DEVICE:-?} dtype=${TTS_DTYPE:-?} model=$TTS_MODEL_NAME port=$PORT"
else
  export TTS_BACKEND="${TTS_BACKEND:-pytorch}"
  export TTS_DEVICE="${TTS_DEVICE:-cpu}"
  export TTS_DTYPE="${TTS_DTYPE:-float32}"
  export TTS_ATTN="${TTS_ATTN:-sdpa}"
  echo "[fae-tts] backend=$TTS_BACKEND device=$TTS_DEVICE model=$TTS_MODEL_NAME port=$PORT"
fi

if [[ -n "${HF_ENDPOINT:-}" ]]; then
  echo "[fae-tts] HF_ENDPOINT=$HF_ENDPOINT"
fi

echo "[fae-tts] listening http://$HOST:$PORT"
echo "[fae-tts] NOTE: first request downloads ~2GB weights — UI will stay silent until that finishes"

exec python -m api.main
