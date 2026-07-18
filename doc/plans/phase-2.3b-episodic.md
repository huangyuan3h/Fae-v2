# Phase 2.3b · Episodic Memory + archival decay

> Status: implemented  
> Base: `init` @ `80a196b` (Phase 2.4 shipped)

## Goal

Life-event log with bidirectional links to facts/archival, inject `[events]`
into recall prompts, and down-weight archival hits unused for 6 months.

## Slice

1. `episodic.py` — SQLite events + links; heuristic detect (搬家 / 换工作 / …)
2. Wire `persist_turn` → detect → save event + link facts; `recall_context` → `[events]`
3. Archival access timestamps + score decay after `ARCHIVAL_DECAY_DAYS` (default 180)
4. `GET /api/memory/events` (+ optional `?session_id=`)
5. Tests + DEVELOPMENT_PLAN 2.3 Episodic checkboxes

## Out of scope

- LLM-based event tagging
- Memory browser UI (2.5)
- Distributed access tracking
