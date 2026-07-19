# Local TTS (Qwen3-TTS / CosyVoice)

FAE synthesizes speech **only** via local TTS (no cloud).

```text
UI → FAE backend POST /api/tts/speak → audio
         └── default: embedded stub (same process as backend :8000)
         └── optional: external OpenAI-compatible server (GPU/CPU weights)
```

## Quick start (`npm run dev`)

From repo root:

```bash
npm run setup   # once
npm run dev     # backend :8000 (+ embedded TTS stub) + UI :3000
```

No separate TTS process. Stub serves a short tone for wiring checks.

`.env` (defaults):

```bash
TTS_EMBED_STUB=true
VLLM_TTS_URL=http://127.0.0.1:8000/v1
TTS_MODEL=qwen3-tts
TTS_VOICE=Cherry
TTS_RESPONSE_FORMAT=wav
```

Optional standalone stub on `:8003` (only if you disable embed):

```bash
npm run dev:tts
```

## Real local Qwen3-TTS (GPU recommended)

1. Install / run an OpenAI-compatible Qwen3-TTS server, for example:
   - [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) + community FastAPI wrappers
   - [malaiwah/qwen3-tts-server](https://github.com/malaiwah/qwen3-tts-server) (`/v1/audio/speech`)
   - Official weights: `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` (lighter) or `1.7B`
2. Point FAE at it:

```bash
TTS_EMBED_STUB=false
VLLM_TTS_URL=http://127.0.0.1:8880/v1   # your server
TTS_MODEL=qwen3-tts
TTS_VOICE=Cherry
TTS_RESPONSE_FORMAT=wav
```

3. Restart FAE backend. Settings → 语音 should show local ready.

VRAM ballpark: ~4–6GB (0.6B), ~6–8GB (1.7B). CPU works but is slow.

## CosyVoice (or any compatible server)

Any server that implements:

```http
POST /v1/audio/speech
{"model","input","voice","response_format"}
→ audio/wav | audio/mpeg | audio/pcm
```

can replace the Qwen3 process — same `VLLM_TTS_URL` with `TTS_EMBED_STUB=false`.
