<!-- docs/map/processes/self-improvement.md -->
# Self-improvement loop

**Trigger:** after `log_execution` on every production pipeline run (`/analyze`, SSE,
`/signal`, live runner); also `GET /api/v1/agents/improvements` and
`POST /agents/improvements/apply`.

**Owner:** `agents/reflection.py` → `agents/improvement.py` →
`backend/services/improvement_service.py` → PostgreSQL.

## Flow

```
trade outcome
  → Reflection: prediction vs outcome, confidence accuracy, lessons
  → Journal: mistakes/lessons persisted
  → Memory: recall + consolidate (Chroma when reachable, in-memory otherwise)
  → Supervisor post-run hook (best-effort, 5 s):
      insert reflection_runs
      → load last 100 committed runs, excluding this row
      → ImprovementEngine.analyze(history=...)
      → insert improvement_records (UUID, unique retry guard)
  → /agents/improvements: list / metrics / apply (mark applied only)
```

The hook is not a graph node. It runs after the graph result is final, catches every
failure, and never changes a trade decision. Backtests intentionally do not record
improvement history.

## Inputs
- `ReflectionOutput`, symbol, request/session IDs, pipeline errors.
- Committed `reflection_runs` history (oldest first, capped at 100).

## Outputs
- `reflection_runs` row with evaluation, confidence accuracy, suggestions, knowledge
  updates, and errors.
- `improvement_records` rows with category, severity, before/after metrics, rationale,
  suggested params, and applied state.
- `GET /api/v1/agents/improvements/metrics` aggregates from committed history.

## Human check
- Suggestions are advisory. Inspect before applying; `apply` only marks the record.
- A suggestion that lowers a safety threshold must be rejected. The execution-rate
  decline record proposes only `max_drawdown_pct: 15.0`; keep the 80% consensus gate
  out of generated parameter suggestions.
- A store outage returns **503** on the API and is logged/skipped by the hook.

## Change impact
- Change a metric → `agents/improvement.py` + `tests/test_improvement.py` + the API type.
- Change persistence → `backend/services/improvement_service.py`,
  `database/schema.sql`, `database/init.sql`, a migration, and this card.
- Add a reflection field → `agents/state.py`, `agents/reflection.py`, the service insert,
  and the frontend type.

## Tests
`tests/test_reflection_agent.py`, `tests/test_improvement.py`,
`tests/test_improvement_service.py`, `tests/test_agents_router.py`,
`tests/test_supervisor.py`, `tests/test_postgres_improvement_integration.py`,
`tests/test_memory_agent.py`, `tests/test_journal_agent.py`.

## Known gaps
A history outage skips that run's record by design; the trade result is unchanged.
Suggestions are not linked to the exact config field they would change, and history is
global across symbols rather than scoped per strategy or account.
