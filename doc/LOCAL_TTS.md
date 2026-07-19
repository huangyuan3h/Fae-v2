# Local TTS (Qwen3-TTS)

FAE synthesizes speech **only** via a local OpenAI-compatible TTS server.
`npm run dev` starts that server on **:8880** together with backend + UI.

```text
npm run dev
  ├─ backend  :8000
  ├─ ui       :3000
  └─ tts      :8880   ← scripts/tts/run.sh (Qwen3-TTS weights)

UI → POST :8000/api/tts/speak (short phrases) → POST :8880/v1/audio/speech → WAV queue
```

The browser **streams LLM tokens** into a hybrid chunker (`SpeechChunkAggregator`):

- Hard ends: `。！？.!?\n…` → enqueue immediately
- Soft ends: ≥28 chars + `，、；;:` → enqueue
- Hard length: ≥40 chars → cut at nearest comma/space
- Idle soft-flush: 250ms without new tokens and ≥8 chars buffered → enqueue
- **Tables and fenced code are not spoken** (display only)

`TtsPlayQueue` keeps up to **4** in-flight synthesizes, waits for **2** ready
clips before the first play (unless the pipeline is drained), and aims to stay
ahead of realtime audio. Per-request cap is **40** characters.

Tune **voice / speed / language** in **Settings → 语音** (stored in
`localStorage`, sent on each `/api/tts/speak`). Process defaults come from `.env`
(`TTS_SPEED=1.2`, etc.).

## First-time setup

```bash
# Once: install server package
npm run setup:tts

# Download weights + short warmup (recommended before chatting)
# Optional China mirror: export HF_ENDPOINT=https://hf-mirror.com
npm run prepare:tts
```

`prepare:tts` checks `~/.cache/huggingface/hub/models--Qwen--Qwen3-TTS-*` for
`.incomplete` files, finishes the download, then synthesizes a short「你好」WAV
and plays it (`afplay`).

Then every day:

```bash
npm run dev
```

Smoke test:

```bash
curl -s http://127.0.0.1:8880/v1/models
curl -s -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"tts-1","input":"你好","voice":"Vivian","response_format":"wav"}' \
  --output /tmp/t.wav && afplay /tmp/t.wav
```

## What is MLX?

**MLX** is Apple’s open-source machine-learning framework for Apple Silicon
(M1/M2/M3/M4). It runs models on the Mac GPU/Neural Engine with memory sharing
that fits unified memory well. For TTS we use the **MLX backend** of
Qwen3-TTS (`TTS_BACKEND=mlx`) plus an **8-bit** checkpoint
(`mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit`), which is usually
faster and lighter than PyTorch MPS float32 on the same Mac.

MLX needs a **separate Python venv** (`.deps/qwen3-tts/.venv-mlx`) because
`mlx-audio` wants Transformers 5 while the official stack pins 4.57.3.
`setup:tts` installs API deps + `mlx-audio` there, then `pip install -e . --no-deps`.

## Defaults (Apple Silicon)

| Item | Value |
|---|---|
| Port | `8880` |
| Backend | **`mlx`** (via `npm run dev` → `scripts/tts/run.sh`) |
| Model | `mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit` |
| Concurrency | `TTS_MAX_CONCURRENT=1` (MLX must stay serial — overlapping gens can wedge) |
| Voice | `Vivian` |

> First MLX start may download 8-bit weights and compile graphs — wait for
> `/v1/models` to respond. If an old PyTorch TTS is still on `:8880`, `run.sh`
> detects the backend mismatch and restarts it.

Override:

```bash
TTS_BACKEND=pytorch TTS_DEVICE=mps npm run dev:tts   # old MPS path
MLX_MODEL_ID=mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit npm run dev:tts
```

If Network shows many `speak` **503** with `MLX backend previously wedged`, the process
is stuck (mlx-audio cold-start bug). Kill `:8880` and restart — `TTS_WARMUP_ON_START=true`
is on by default for MLX.


## FAE `.env`

```bash
VLLM_TTS_URL=http://127.0.0.1:8880/v1
TTS_MODEL=tts-1
TTS_VOICE=Vivian
TTS_LANGUAGE=Chinese
TTS_SPEED=1.2
TTS_RESPONSE_FORMAT=wav
TTS_TIMEOUT_S=300
```

Useful API:

| Endpoint | Role |
|---|---|
| `POST /api/tts/speak` | Body: `{ text, voice?, speed?, language? }` — per-request cap ~40 chars |
| `GET /api/tts/voices` | Upstream or builtin CustomVoice list |
| `GET /api/tts/status` | Ready flag + defaults (`speed`, `language`, `voice`) |

## Layout

| Path | Role |
|---|---|
| `scripts/tts/setup.sh` | Clone server into `.deps/qwen3-tts`; Mac also installs `.venv-mlx` |
| `scripts/tts/run.sh` | Start `python -m api.main` on `:8880` (Mac → MLX, concurrent=2) |
| `scripts/tts/prepare.sh` | Download MLX/pytorch weights + warmup speak |
| `.deps/qwen3-tts/.venv-mlx` | Apple Silicon MLX env (`pip install -e ".[api,mlx]"`) |
| `.deps/qwen3-tts/` | Local checkout (gitignored) |
| `ui/src/lib/sentence-agg.ts` | Hybrid phrase chunker + idle soft-flush |
| `ui/src/lib/tts-prefs.ts` | Browser voice/speed/language prefs |

## Notes

- Prefer `npm run prepare:tts` after setup so the first chat is not stuck on weight download.
- First synthesis downloads model weights — can take several minutes.
- WAV does not need FFmpeg; MP3 does (`brew install ffmpeg`).
- If `:8880` is already healthy **and** `backend.name` matches the desired backend, `dev:tts` **reuses** it; otherwise it restarts (so an old pytorch process will be replaced by MLX).
- Stub-only beep server (no weights): `npm run dev:stub` on `:8003` — not used by default.
- Interrupt / barge-in clears the play queue immediately.
