---
name: weather_briefing
description: Answer live weather questions using get_weather and the user's city
triggers:
  - 天气
  - 气温
  - 下雨
  - 下雪
  - 伞
  - weather
  - temperature
  - forecast
  - raining
  - umbrella
requires_tools:
  - get_weather
priority: 8
max_context_tokens: 600
enabled: true
requires_approval: false
cooldown_seconds: 0
load_strategy: trigger_based
---

# Weather Briefing Skill

## Role
Give accurate, concise live weather answers. Never invent conditions.

## Workflow
1. Resolve the city: use the user's message, else Default city from `<fae_context>` / memory `City`
2. Call `get_weather` (omit city only when a default is known)
3. Summarize current conditions + today's high/low + rain chance in 2–4 short sentences
4. Optionally add one practical tip (umbrella, jacket) when relevant

## Boundaries
- If `get_weather` fails or city is unknown, ask for the city — do not guess real-time weather
- Prefer the user's language (中文 / English)
- Keep replies speakable for voice (no long tables)
