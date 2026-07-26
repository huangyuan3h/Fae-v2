## 0.6.0 — 2026-07-26 (Context Engineering R1–R6)

All six recommendations from `doc/archive/CONTEXT_ENGINEERING_RESEARCH_2026-07-26.md`
are now landed in code. The research document is moved to archive; the active
context-engineering overview is `doc/design/CONTEXT_ENGINEERING.md`.

### Highlights

- **R1 — Anthropic `cache_control`**: `LLMConfig.cache_control` field;
  `provider.py` auto-detects Anthropic endpoints (base_url / `anthropic-version`
  header) and injects `cache_control: ephemeral` markers on the last system
  block + last tool. TTL configurable (`auto` / `off` / `ephemeral-5m` /
  `ephemeral-1h`). Cost reduction -50% to -90%, first-token latency -75%.
- **R2 — LLM rolling summary**: `fae/memory/summarizer.py::RollingSummarizer`
  compresses oldest hot recall turns into a structured JSON summary via a cheap
  LLM (default proactive / server-side model). Writes the summary to the
  Letta `current` block, mirrors to archival, and promotes extracted facts.
  Triggers at 30 turns / 9000 chars by default; keeps last 6 verbatim.
- **R3 — Pipecat `LLMContextSummarizer` (Daily path)**: opt-in via
  `daily_context_summary_enabled`; `fae/pipecat/summarizer_bridge.py`
  builds the `LLMAssistantAggregatorParams` for the Daily voice pipeline.
- **R4 — Letta-style reflection subagent**: new `reflection` builtin in
  `agent/subagents/builtins.py`; `fae/memory/reflection.py::SubagentReflectionRunner`
  delegates sleeptime consolidation to it; failures fall back to the existing
  heuristic bullet path.
- **R5 — Tool-result offload (Deep Agents FilesystemMiddleware port)**:
  `fae/agent/tool_offload.py::ToolOffloader` writes oversized tool results
  (default > 8000 chars) to `.data/tool-offload/*.json` and replaces the
  in-prompt body with a path pointer + head/tail preview. Wired into all
  tool result injection points (coding / weather / subagent) on HTTP chat,
  WS chat, and Telegram inbound.
- **R6 — Contextual Retrieval (Anthropic §6.3)**: opt-in via
  `contextual_retrieval_enabled`; `fae/memory/contextual.py::ContextualizingArchival`
  wraps the archival backend so each chunk gets a 50–100 token context line
  before embedding. Cache-friendly: the reference document rides with
  `cache_control: ephemeral` so chunk-contextualization calls are essentially
  free on Anthropic.
- **Monitoring**: `GET /api/memory/stats` now exposes `cache_health`
  (status / ratio / signal) and a `context_engineering` subtree with on/off
  flags for every feature.

### Notes

- Existing `MemoryCompactor` (heuristic chunk → archival) stays in place
  as the safety net; R2 sits *above* it so failed summarizations never lose
  history.
- `LLMConfig.prompt_cache_key` (OpenAI/Azure) was already wired and
  unchanged — R1 extends the same pattern to Anthropic-style endpoints.
- R6 / R3 default to off (opt-in via `.env`): they add an LLM call per
  trigger and only pay off when the host endpoint honours
  `cache_control`. Flip the relevant `_ENABLED` flag to test.

## 0.5.0 — 2026-07-25 (Next.js 16 alignment)

Frontend runtime and build tooling are aligned on the Next.js 16 stable line.

### Highlights

- **Next.js**: upgraded from 15.5.20 to 16.2.11 with React / React DOM 19.2.8
- **Tooling**: TypeScript 5.9.3 and ESLint 9.39.5 retained for a conservative migration; `eslint-config-next` is aligned to 16.2.11
- **Runtime**: Node.js 24.4.1+ and pnpm 10.28.2 are now the supported UI build baseline
- **Build validation**: added UI typecheck, standalone artifact assertion, native flat ESLint config, and viewport metadata export
- **Dependencies**: updated TanStack Query to 5.101.4, Recharts to 3.10.0, and Node type definitions to 24.13.3

### Notes

- `@fae/client` remains a source-only package compiled through `transpilePackages`
- Next.js 16, React, React DOM, and `eslint-config-next` are intentionally kept on matching stable release lines

## 0.4.0 — 2026-07-19 (P7 Client contract)

Thin-client contract: server LLM key default for chat, capability discovery, optional client token, reference Web UI, `@fae/client` SDK.

### Highlights

- **LLM merge**: empty client `api_key` → `DASHSCOPE` / `PROACTIVE_LLM_*` on `/api/chat`, `/ws/chat`, `/api/test-connection`
- **`GET /api/capabilities`**: channels / modes / tools / server LLM / auth flags
- **`FAE_CLIENT_TOKEN`**: optional Bearer (or WS `access_token`); health/ready/capabilities stay public
- **Web Reference Client**: no browser Key required to chat; Models Key is optional override
- **`sdk/typescript` (`@fae/client`)**: `createClient` / `chatStream` / `getCapabilities` / notifications hook

### Notes

- API compatibility: additive fields only; no `/v1` prefix yet
- OAuth, full REST SDK coverage, and device binding productization deferred

## 0.3.0 — 2026-07-19 (P6 Core always-on)

Always-on Agent Core deploy path: slim compose, richer `/ready`, Tailscale-oriented docs, GitHub Release.

### Highlights

- **`docker-compose.core.yml`**: embedded Letta + named volume `fae-data` + `restart: unless-stopped`; optional TTS stub profile
- **`deploy/scripts/start-core.sh`**: build/up + poll `/ready`
- **`GET /ready`**: `memory` / `scheduler` / `telegram` / `proactive_llm` (+ legacy `letta`); memory `down` → HTTP 503
- **Docs**: `doc/operations/DEPLOY.md` 30-minute checklist; `.env.example` Always-on Core block; README pointer
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
