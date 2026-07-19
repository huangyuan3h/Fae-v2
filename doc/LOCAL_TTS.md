# Local TTS (Qwen3-TTS)

FAE synthesizes speech **only** via a local OpenAI-compatible TTS server.
`npm run dev` starts that server on **:8880** together with backend + UI.

```text
npm run dev
  ├─ backend  :8000
  ├─ ui       :3000
  └─ tts      :8880   ← scripts/tts/run.sh (Qwen3-TTS weights)

UI → POST :8000/api/tts/speak (per sentence) → POST :8880/v1/audio/speech → WAV queue
```

The browser **streams LLM tokens**, splits on sentence boundaries (`。！？.!?\n`),
and synthesizes/plays each short clip while prefetching the next (1–2 in flight).
This cuts time-to-first-audio vs waiting for the full reply.

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

## Defaults (Apple Silicon)

| Item | Value |
|---|---|
| Port | `8880` |
| Backend | `pytorch` + `TTS_DEVICE=mps` |
| Model | `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` |
| Voice | `Vivian` |

> `official` backend only picks CUDA or CPU (ignores MPS), so Mac uses `pytorch`+MPS.
> First chat after a fresh install downloads ~2GB weights — **no audio until that finishes**.

Override:

```bash
TTS_DEVICE=cpu npm run dev:tts          # force CPU
TTS_MODEL_NAME=Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice npm run dev:tts
```

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
| `POST /api/tts/speak` | Body: `{ text, voice?, speed?, language? }` — per-request cap ~120 chars |
| `GET /api/tts/voices` | Upstream or builtin CustomVoice list |
| `GET /api/tts/status` | Ready flag + defaults (`speed`, `language`, `voice`) |

## Layout

| Path | Role |
|---|---|
| `scripts/tts/setup.sh` | Clone [Qwen3-TTS-Openai-Fastapi](https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi) into `.deps/qwen3-tts` + install |
| `scripts/tts/run.sh` | Start `python -m api.main` on `:8880` |
| `scripts/tts/prepare.sh` | Verify HF cache + warmup speak (`npm run prepare:tts`) |
| `.deps/qwen3-tts/` | Local checkout (gitignored) |
| `ui/src/lib/sentence-agg.ts` | Sentence splitter for stream-to-speak |
| `ui/src/lib/tts-prefs.ts` | Browser voice/speed/language prefs |

## Notes

- Prefer `npm run prepare:tts` after setup so the first chat is not stuck on weight download.
- First synthesis downloads model weights — can take several minutes.
- WAV does not need FFmpeg; MP3 does (`brew install ffmpeg`).
- If `:8880` is already a healthy TTS from a previous run, `dev:tts` **reuses** it (no EADDRINUSE crash).
- Stub-only beep server (no weights): `npm run dev:stub` on `:8003` — not used by default.
- Interrupt / barge-in clears the play queue immediately.
