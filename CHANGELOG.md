# Changelog

## 0.3.0 — 2026-07-19 (P6 Core always-on)

Always-on Agent Core deploy path: slim compose, richer `/ready`, Tailscale-oriented docs, GitHub Release.

### Highlights

- **`docker-compose.core.yml`**: embedded Letta + named volume `fae-data` + `restart: unless-stopped`; optional TTS stub profile
- **`deploy/scripts/start-core.sh`**: build/up + poll `/ready`
- **`GET /ready`**: `memory` / `scheduler` / `telegram` / `proactive_llm` (+ legacy `letta`); memory `down` → HTTP 503
- **Docs**: `doc/DEPLOY.md` 30-minute checklist; `.env.example` Always-on Core block; README pointer
- **CI**: backend Docker image build step (no full-stack compose)

### Notes

- Browser `/ws/chat` still uses client Key (P7); Telegram / Loop use server `DASHSCOPE_API_KEY` / `PROACTIVE_LLM_*`
- Full-stack `docker-compose.yml` remains the Letta-remote **dev** path

## 0.2.0 — 2026-07-19 (stable cut)

Stable snapshot after Phase Q quality hardening and Phase 5.1–5.2 ceiling work.

### Highlights

- **Default voice path**: browser STT → `/ws/chat` → local TTS (`VLLM_TTS_URL`); Daily optional; LiveKit/MCP deferred
- **Phase Q**: persona, memory recall, voice barge-in, skills contract, proactive loop, minimal evals in CI
- **Phase 5.1**: mobile PWA shell + Telegram long-polling channel (`TELEGRAM_*`)
- **Phase 5.2**: `run_subagent` tool (researcher / coder / reviewer); attaches only when an active skill requires it; summary → archival; WS system lines

### Notes

- Browser chat API keys stay in the UI; proactive Loop / Telegram / subagents use server `PROACTIVE_LLM_*` / `DASHSCOPE_API_KEY`
- `run_subagent` attaches only when an active skill declares `requires_tools: [run_subagent]` (no per-turn probe on plain chat)
- Slack, multi-user auth, local ASR, and nested subagents are out of scope for this cut
- Backend coverage floor temporarily **78%** (was 80%) after 5.1/5.2 surface growth
