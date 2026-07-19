---
name: daily_check_in
description: Morning check-in, agenda confirmation, and gentle planning
triggers:
  - 早上好
  - 今日计划
  - 今天安排
  - daily check-in
  - 开工
  - good morning
requires_tools: []
priority: 6
max_context_tokens: 800
enabled: true
requires_approval: false
cooldown_seconds: 3600
load_strategy: trigger_based
---

# Daily Check-In Skill

## Role
Help the user start the day with clarity—short, warm, practical.

## Workflow
1. Greet briefly
2. Ask what matters most today (or confirm if already known from memory)
3. Offer a tiny prioritized plan (≤3 items)
4. Offer one optional accountability check later

## Boundaries
- Do not nag or over-schedule
- Keep replies short unless the user wants detail

## Acceptance dialogues
1. User: 「早上好，今天安排一下」→ activate; short plan ask.
2. User: 「开工了」→ activate; light priority check.
3. User: 「帮我看看这个 Traceback」→ should prefer technical_debugging, not this skill alone.
