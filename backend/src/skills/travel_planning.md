---
name: travel_planning
description: Plan trips using preferences and constraints from conversation/memory
triggers:
  - 旅行
  - 行程
  - 机票
  - 酒店
  - travel plan
  - itinerary
  - 出差
requires_tools: []
priority: 7
max_context_tokens: 1200
enabled: true
requires_approval: false
cooldown_seconds: 60
load_strategy: trigger_based
---

# Travel Planning Skill

## Role
Plan trips that respect budget, dates, and known preferences.

## Workflow
1. Confirm destination, dates, companions, budget
2. Propose a day-by-day skeleton
3. Call out open risks (visas, weather, transfers)
4. Remember durable preferences when the user confirms them

## Memory write-back
- Durable prefs (pace, budget band, dietary, home airport) → suggest / rely on `[human]` once the user confirms
- Trip-in-progress (dates, destination this week) → keep in `[current]` until the trip ends
- Do not invent bookings; mark uncertain facts clearly

## Boundaries
- Do not book or pay for anything
- Mark uncertain facts clearly

## Acceptance dialogues
1. User: 「帮我规划下周去京都的旅行」→ activate; ask missing dates/budget if needed, then outline days.
2. User: 「出差上海三天，酒店和交通怎么安排」→ activate; practical itinerary.
3. User: 「今天心情不错」→ should NOT activate.
