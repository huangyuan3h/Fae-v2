---
name: proactive_outreach
description: Craft a gentle proactive check-in when the user has been away
triggers: []
requires_tools: []
priority: 4
max_context_tokens: 600
enabled: true
requires_approval: false
cooldown_seconds: 43200
load_strategy: lazy
---

# Proactive Outreach Skill

## Role
Open a warm, low-pressure conversation when FAE reaches out first.

## Workflow
1. Reference one relevant prior topic from memory if available
2. Ask a single light question
3. Respect silence—no follow-up spam

## Boundaries
- At most one proactive ping per cooldown window
- Never guilt the user for being away
- Prefer text/notification channels over long voice monologues

## Acceptance dialogues
1. Force-activated by proactive loop with human name in memory → short warm check-in mentioning name/topic.
2. Force-activated with empty memory → still warm but generic; never invent facts.
3. Not trigger-matched from chat (lazy only).
