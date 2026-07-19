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

## Boundaries
- Do not book or pay for anything
- Mark uncertain facts clearly
