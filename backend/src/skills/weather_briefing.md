---
name: weather_briefing
description: Answer live weather using get_weather; learn home city into human memory
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
Home city is a durable fact in the `[human]` memory block (plain language).

## Workflow
1. Resolve city in this order:
   - City named in the current user message
   - Home city from `<fae_memory>` / `<fae_context>` (e.g. "Lives in 北京.")
2. If still unknown: ask **once**, briefly — e.g. 「你在哪个城市？我说了会记住。」
   Do not call `get_weather` until you have a city. Stop after asking.
3. When the user answers with a city (even a short reply like「上海」):
   - Call `get_weather` with that city
   - Treat it as remembered (the system will persist "Lives in …" into human memory)
4. If the user corrects location (「不对，是杭州」/「我搬到深圳了」):
   - Use the new city for weather
   - Acknowledge the update briefly
5. Summarize current + today's high/low + rain chance in 2–4 short sentences

## Boundaries
- Never guess real-time weather without `get_weather`
- Prefer the user's language (中文 / English)
- Keep replies speakable for voice
- Do not re-ask for city every turn once it is in memory
