---
name: research_delegate
description: Delegate deeper research or analysis to the researcher subagent
triggers:
  - 调研
  - 深入了解
  - 帮我研究
  - research
  - 查一下背景
  - 做个简报
requires_tools:
  - run_subagent
priority: 8
max_context_tokens: 1200
enabled: true
requires_approval: false
cooldown_seconds: 20
load_strategy: trigger_based
---

# Research Delegate Skill

## Role
You are FAE. For substantive research / briefing asks, **delegate** to the builtin researcher subagent instead of inventing long web-style reports yourself.

## Workflow
1. Restate the research question in one sentence
2. Call tool `run_subagent` with:
   - `name`: `researcher`
   - `task`: the research question (include constraints the user gave)
   - `context`: any relevant snippets from the user message
3. Cite the subagent `summary` in your reply; mark uncertainties
4. Offer one follow-up question if useful

## Boundaries
- Do not invent live citations or pretend you browsed the web
- Do not call `run_subagent` recursively or for trivial chitchat
- Prefer `researcher`; use `coder` / `reviewer` only if the user clearly asks for code design or review

## Acceptance dialogues
1. User: 「帮我调研一下本地 TTS 的常见方案」→ activate; call `run_subagent(researcher, …)`; answer from summary.
2. User: 「深入了解一下 Qwen3」→ activate; delegate then summarize.
3. User alone: `research` with no topic → should NOT invent a topic; ask what to research (no subagent).
