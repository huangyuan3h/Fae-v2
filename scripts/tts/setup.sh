#!/usr/bin/env bash
# Install the OpenAI-compatible Qwen3-TTS server into .deps/qwen3-tts (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEP_DIR="${FAE_TTS_DIR:-$ROOT/.deps/qwen3-tts}"
REPO_URL="${FAE_TTS_REPO:-https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi.git}"
PYTHON_BIN="${FAE_TTS_PYTHON:-python3.12}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

echo "[fae-tts] target: $DEP_DIR"
echo "[fae-tts] python: $PYTHON_BIN ($("$PYTHON_BIN" -V 2>&1))"

mkdir -p "$(dirname "$DEP_DIR")"

if [[ ! -d "$DEP_DIR/.git" ]]; then
  echo "[fae-tts] cloning $REPO_URL ..."
  git clone --depth 1 "$REPO_URL" "$DEP_DIR"
else
  echo "[fae-tts] repo already present"
fi

cd "$DEP_DIR"

if [[ ! -d .venv ]]; then
  echo "[fae-tts] creating venv ..."
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip wheel

# mlx extras currently conflict with qwen-tts pin of transformers==4.57.3
# (mlx-audio wants huggingface_hub>=1 / transformers 5). Use official API stack;
# on Apple Silicon PyTorch can still use MPS when available.
echo "[fae-tts] installing .[api] (OpenAI-compatible server + official backend)"
pip install -e ".[api]"

mkdir -p "$ROOT/.deps"
echo "api" > "$ROOT/.deps/qwen3-tts.ready"
echo "[fae-tts] setup complete → $DEP_DIR"
echo "[fae-tts] next: npm run dev   (starts TTS on :8880)"
