#!/usr/bin/env bash
# Start OpenAI-compatible Qwen3-TTS on :8880 for npm run dev.
# Apple Silicon defaults to MLX 1.7B CustomVoice bf16 (less quant noise than 8bit).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEP_DIR="${FAE_TTS_DIR:-$ROOT/.deps/qwen3-tts}"
READY="$ROOT/.deps/qwen3-tts.ready"
PORT="${PORT:-${FAE_TTS_PORT:-8880}}"
HOST="${HOST:-127.0.0.1}"

OS="$(uname -s)"
ARCH="$(uname -m)"
IS_APPLE_SILICON=0
if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
  IS_APPLE_SILICON=1
fi

# Desired defaults (overridable via env).
# bf16 ≈ full MLX precision (~4.5GB); 8bit is smaller/faster but sandier.
DEFAULT_MLX_MODEL="mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-bf16"
if [[ "$IS_APPLE_SILICON" -eq 1 ]]; then
  export TTS_BACKEND="${TTS_BACKEND:-mlx}"
  export MLX_MODEL_ID="${MLX_MODEL_ID:-$DEFAULT_MLX_MODEL}"
  export TTS_MODEL_NAME="${TTS_MODEL_NAME:-$MLX_MODEL_ID}"
  # mlx-audio 0.3/0.4 can wedge the whole process if two gens overlap — keep 1.
  export TTS_MAX_CONCURRENT="${TTS_MAX_CONCURRENT:-1}"
  export TTS_LAZY_LOAD="${TTS_LAZY_LOAD:-false}"
  export TTS_WARMUP_ON_START="${TTS_WARMUP_ON_START:-true}"
  VENV_DIR="${DEP_DIR}/.venv-mlx"
else
  export TTS_BACKEND="${TTS_BACKEND:-pytorch}"
  export TTS_DEVICE="${TTS_DEVICE:-cpu}"
  export TTS_DTYPE="${TTS_DTYPE:-float32}"
  export TTS_ATTN="${TTS_ATTN:-sdpa}"
  export TTS_MODEL_NAME="${TTS_MODEL_NAME:-Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice}"
  export TTS_MAX_CONCURRENT="${TTS_MAX_CONCURRENT:-2}"
  export TTS_LAZY_LOAD="${TTS_LAZY_LOAD:-true}"
  VENV_DIR="${DEP_DIR}/.venv"
fi

tts_models_ok() {
  curl -sf --max-time 2 "http://${HOST}:${PORT}/v1/models" 2>/dev/null \
    | grep -q '"object"[[:space:]]*:[[:space:]]*"list"'
}

tts_health_field() {
  # Usage: tts_health_field name|model_id
  local field="$1"
  curl -sf --max-time 2 "http://${HOST}:${PORT}/health" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); b=d.get("backend") or {}; print(b.get(sys.argv[1]) or "")' "$field" \
    2>/dev/null || true
}

free_stale_listener() {
  local pids pid args
  pids="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "$pids" ]] && return 0
  for pid in $pids; do
    args="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    if echo "$args" | grep -qE 'api\.main|qwen3-tts|Qwen3-TTS|uvicorn'; then
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

ensure_setup() {
  local need=0
  if [[ ! -f "$READY" ]]; then
    need=1
  fi
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    need=1
  fi
  if [[ "$need" -eq 1 ]]; then
    echo "[fae-tts] server / venv missing — running setup (first time may take a while) ..."
    bash "$ROOT/scripts/tts/setup.sh"
  fi
}

ensure_setup

# Reuse only if healthy AND backend+model already match (avoid keeping 0.6B / pytorch).
if tts_models_ok; then
  current_backend="$(tts_health_field name)"
  current_model="$(tts_health_field model_id)"
  want_model="${MLX_MODEL_ID:-$TTS_MODEL_NAME}"
  if [[ "$current_backend" == "$TTS_BACKEND" ]] && \
     { [[ "$TTS_BACKEND" != "mlx" ]] || [[ "$current_model" == "$want_model" ]]; }; then
    echo "[fae-tts] already healthy on http://${HOST}:${PORT} backend=$current_backend model=${current_model:-n/a} — reusing"
    echo "[fae-tts] (Ctrl+C stops npm run dev only; TTS process stays up)"
    while tts_models_ok; do
      sleep 30
    done
    echo "[fae-tts] upstream gone — will start a new server"
  else
    echo "[fae-tts] :${PORT} is up but backend='${current_backend:-unknown}' model='${current_model:-unknown}'"
    echo "[fae-tts] want backend=$TTS_BACKEND model=$want_model — restarting"
    free_stale_listener
  fi
fi

if ! tts_models_ok; then
  free_stale_listener
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
cd "$DEP_DIR"

export HOST
export PORT
export WORKERS="${WORKERS:-1}"
export CORS_ORIGINS="${CORS_ORIGINS:-*}"

if [[ "$TTS_BACKEND" == "mlx" ]]; then
  # Quick import check; guide user if mlx extras missing.
  if ! python -c 'import mlx_audio' 2>/dev/null; then
    echo "[fae-tts] ERROR: mlx-audio not found in ${VENV_DIR}"
    echo "[fae-tts] run: npm run setup:tts"
    exit 1
  fi
  echo "[fae-tts] darwin MLX backend model=$MLX_MODEL_ID concurrent=$TTS_MAX_CONCURRENT lazy=$TTS_LAZY_LOAD port=$PORT"
else
  echo "[fae-tts] backend=$TTS_BACKEND device=${TTS_DEVICE:-?} model=$TTS_MODEL_NAME concurrent=$TTS_MAX_CONCURRENT port=$PORT"
fi

if [[ -n "${HF_ENDPOINT:-}" ]]; then
  echo "[fae-tts] HF_ENDPOINT=$HF_ENDPOINT"
fi

echo "[fae-tts] listening http://$HOST:$PORT"
echo "[fae-tts] NOTE: first MLX/pytorch load may download weights — UI silent until ready"

exec python -m api.main
