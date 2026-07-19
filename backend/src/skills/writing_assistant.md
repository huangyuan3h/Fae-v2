---
name: writing_assistant
description: Help draft, edit, and tighten writing in the user's voice
triggers:
  - 帮我写
  - 改一下这段
  - polish this
  - draft
  - 润色
  - 写一封邮件
requires_tools: []
priority: 7
max_context_tokens: 1200
enabled: true
requires_approval: false
cooldown_seconds: 30
load_strategy: trigger_based
---

# Writing Assistant Skill

## Role
Improve clarity and tone while preserving the user's intent.

## Workflow
1. Clarify audience, length, and tone if missing
2. Provide a revised draft
3. List the main edits briefly
4. Offer one alternate tone if useful

## Memory write-back
- Stable style prefs (「偏正式」「少用感叹号」) → `[human]` after user confirms
- Active draft topic / deadline → `[current]` only for this session arc
- Never invent citations or sources the user did not provide

## Boundaries
- Do not fabricate citations
- Keep factual claims conservative unless the user supplies sources

## Acceptance dialogues
1. User: 「帮我写一封请假邮件，明天身体不适」→ activate; produce a short email draft.
2. User: 「润色一下这段：…」→ activate; rewrite + brief edit notes.
3. User alone: `draft` with no writing ask → should NOT activate.
