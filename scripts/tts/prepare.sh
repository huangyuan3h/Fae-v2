#!/usr/bin/env bash
# Verify / download Qwen3-TTS weights and warm up :8880 with a short sample.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEP_DIR="${FAE_TTS_DIR:-$ROOT/.deps/qwen3-tts}"
READY="$ROOT/.deps/qwen3-tts.ready"
MODEL="${TTS_MODEL_NAME:-Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-${FAE_TTS_PORT:-8880}}"
CACHE="$HOME/.cache/huggingface/hub/models--${MODEL//\//--}"

echo "[fae-tts] prepare model=$MODEL"

if [[ ! -f "$READY" || ! -x "$DEP_DIR/.venv/bin/python" ]]; then
  echo "[fae-tts] server package missing — running setup first"
  bash "$ROOT/scripts/tts/setup.sh"
fi

# shellcheck disable=SC1091
source "$DEP_DIR/.venv/bin/activate"

incomplete="$(find "$CACHE" -name '*.incomplete' 2>/dev/null | head -5 || true)"
if [[ -n "$incomplete" ]]; then
  echo "[fae-tts] incomplete downloads still present — resuming HF download"
fi

echo "[fae-tts] ensuring weights via huggingface_hub ..."
python - <<PY
from huggingface_hub import snapshot_download
path = snapshot_download(
    repo_id="${MODEL}",
    resume_download=True,
)
print("[fae-tts] weights at", path)
PY

if [[ -d "$CACHE" ]]; then
  du -sh "$CACHE" | awk '{print "[fae-tts] cache size:", $1}'
fi
left="$(find "$CACHE" -name '*.incomplete' 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$left" != "0" ]]; then
  echo "[fae-tts] ERROR: still have $left incomplete blob(s)"
  exit 1
fi
echo "[fae-tts] weights OK (no .incomplete files)"

# Start TTS in background if not already healthy
need_stop=0
if ! curl -sf --max-time 2 "http://${HOST}:${PORT}/v1/models" >/dev/null; then
  echo "[fae-tts] starting server for warmup on :${PORT}"
  bash "$ROOT/scripts/tts/run.sh" >/tmp/fae-tts-prepare.log 2>&1 &
  need_stop=$!
  for i in $(seq 1 60); do
    if curl -sf --max-time 2 "http://${HOST}:${PORT}/v1/models" >/dev/null; then
      break
    fi
    sleep 1
  done
fi

if ! curl -sf --max-time 2 "http://${HOST}:${PORT}/v1/models" >/dev/null; then
  echo "[fae-tts] ERROR: server not reachable at http://${HOST}:${PORT}"
  [[ "$need_stop" != "0" ]] && kill "$need_stop" 2>/dev/null || true
  exit 1
fi

echo "[fae-tts] warming up with short Chinese sample (may take ~30s first time) ..."
code="$(curl -sS -m 300 -o /tmp/fae-tts-warmup.wav -w '%{http_code}' \
  -X POST "http://${HOST}:${PORT}/v1/audio/speech" \
  -H 'Content-Type: application/json' \
  -d '{"model":"tts-1","input":"你好，语音已就绪。","voice":"Vivian","language":"Chinese","response_format":"wav"}')"

if [[ "$code" != "200" ]]; then
  echo "[fae-tts] ERROR: warmup HTTP $code"
  head -c 400 /tmp/fae-tts-warmup.wav 2>/dev/null || true
  echo
  [[ "$need_stop" != "0" ]] && kill "$need_stop" 2>/dev/null || true
  exit 1
fi

if ! file /tmp/fae-tts-warmup.wav | grep -q 'WAVE audio'; then
  echo "[fae-tts] ERROR: warmup did not return WAV"
  file /tmp/fae-tts-warmup.wav
  [[ "$need_stop" != "0" ]] && kill "$need_stop" 2>/dev/null || true
  exit 1
fi

sz="$(wc -c </tmp/fae-tts-warmup.wav | tr -d ' ')"
echo "[fae-tts] warmup OK — /tmp/fae-tts-warmup.wav ($sz bytes)"
if command -v afplay >/dev/null 2>&1; then
  echo "[fae-tts] playing sample ..."
  afplay /tmp/fae-tts-warmup.wav || true
fi

if [[ "$need_stop" != "0" ]]; then
  echo "[fae-tts] stopping temporary server pid=$need_stop"
  # Kill the run.sh tree (python -m api.main)
  pkill -P "$need_stop" 2>/dev/null || true
  kill "$need_stop" 2>/dev/null || true
fi

echo "[fae-tts] PREPARE COMPLETE — safe to npm run dev"
