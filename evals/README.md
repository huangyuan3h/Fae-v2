# FAE-v2 Evals (Phase Q.5)

Minimal regression cases for MQ-2 / MQ-3 / default voice path.  
**Not** a full ASR/TTS corpus.

## Layout

```text
evals/
├── agent/
│   ├── skill-trigger.json     # skill match positive / negative
│   └── memory-recall.json     # name / city / dietary → recall
└── e2e/
    └── ws_voice_round_no_daily.json   # WS chat + TTS stub metadata
```

## How to run

Cases are loaded by pytest under `backend/tests/test_evals_*.py` (CI already runs `uv run pytest` in `backend/`):

```bash
cd backend && uv run pytest tests/test_evals_*.py -q
```

No `DAILY_API_KEY`, no live DashScope, no real Qwen3-TTS required (TTS uses in-process stub).

## Keeping skill-trigger in sync

`evals/agent/skill-trigger.json` mirrors `backend/tests/fixtures/skill_trigger_cases.json`.  
When changing matcher expectations, update both (or copy fixture → evals).
