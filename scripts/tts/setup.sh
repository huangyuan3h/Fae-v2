#!/usr/bin/env bash
# Install the OpenAI-compatible Qwen3-TTS server into .deps/qwen3-tts (gitignored).
# On Apple Silicon also installs a dedicated .venv-mlx for the MLX backend.
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
  echo "[fae-tts] creating .venv (pytorch / official stack) ..."
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip wheel

# mlx-audio wants Transformers 5; official qwen-tts pins 4.57.3 — keep separate.
echo "[fae-tts] installing .[api] into .venv"
pip install -e ".[api]"
deactivate

OS="$(uname -s)"
ARCH="$(uname -m)"
if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
  # mlx-audio needs Transformers 5 / hub>=1; qwen-tts pins Transformers 4.57.3.
  # Use a dedicated venv and install the package with --no-deps.
  if [[ ! -d .venv-mlx ]]; then
    echo "[fae-tts] creating .venv-mlx (Apple MLX stack) ..."
    "$PYTHON_BIN" -m venv .venv-mlx
  fi
  # shellcheck disable=SC1091
  source .venv-mlx/bin/activate
  python -m pip install --upgrade pip wheel
  echo "[fae-tts] installing MLX stack into .venv-mlx (mlx-audio + API deps)"
  pip install \
    "mlx-audio>=0.3.0" \
    "huggingface_hub[hf_xet]>=1.0" \
    "fastapi>=0.109.0" \
    "uvicorn[standard]>=0.27.0" \
    "python-multipart" \
    "pydantic>=2.0.0" \
    "inflect" \
    "aiofiles" \
    "pydub" \
    "httpx>=0.24.0" \
    "numpy>=1.24" \
    "librosa" \
    "soundfile" \
    "einops" \
    "PyYAML>=6.0" \
    "requests" \
    "tqdm"
  echo "[fae-tts] installing qwen-tts package code (--no-deps) into .venv-mlx"
  pip install -e . --no-deps
  python -c 'import mlx_audio, api.main; print("[fae-tts] mlx import OK")'
  deactivate
  echo "api+mlx" > "$ROOT/.deps/qwen3-tts.ready"
else
  echo "api" > "$ROOT/.deps/qwen3-tts.ready"
fi

mkdir -p "$ROOT/.deps"
echo "[fae-tts] setup complete → $DEP_DIR"
if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
  echo "[fae-tts] Mac default: TTS_BACKEND=mlx via .venv-mlx (npm run dev)"
else
  echo "[fae-tts] next: npm run dev   (starts TTS on :8880)"
fi
