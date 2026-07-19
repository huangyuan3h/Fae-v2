# FAE-v2 UI

Next.js app for FAE-v2 (voice chat, memory, skills, schedules, settings).

**Canonical docs**: [../README.md](../README.md) · [../doc/ARCHITECTURE.md](../doc/ARCHITECTURE.md)

## Current surfaces

| Route | Purpose |
|---|---|
| `/` | Chat + browser STT + local TTS (default path) |
| `/memory` | Timeline / facts / search |
| `/skills` | Skill editor + MQ-2 trigger presets |
| `/schedules` | NL parse → confirm → create |
| `/settings` | Persona, profile, models, voice, notifications |

Default path does **not** require Daily. Use `?debug=1` on `/` for voice metrics.

## Develop

From repo root (preferred):

```bash
npm run dev
```

Or in this package:

```bash
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). Backend expected at `:8000` (see root `.env` / `NEXT_PUBLIC_*` if configured).

## Scripts

```bash
pnpm lint
pnpm build
```
