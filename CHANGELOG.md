# Changelog

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
