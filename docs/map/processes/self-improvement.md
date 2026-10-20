<!-- docs/map/processes/self-improvement.md -->
# Self-improvement loop

**Trigger:** after the Memory node on every pipeline run; also
`GET /api/v1/agents/improvements` and `POST /agents/improvements/apply`.

**Owner:** `agents/reflection.py` → `agents/improvement.py` → `agents/memory.py`.

## Flow

```
trade outcome
  → Reflection: prediction vs outcome, confidence accuracy, lessons
  → Journal: mistakes/lessons persisted
  → Memory: recall + consolidate (Chroma when reachable, in-memory otherwise)
  → Improvement: trend detection across recent runs, parameter suggestions
  → /agents/improvements: read/apply (mark applied; does not mutate config)
```

## Inputs
- Execution result, entry/exit prices, agent confidences, prior reflections.
- `ImprovementEngine` history (in-process).

## Outputs
- `ReflectionOutput`, `MemoryOutput`, improvement records with suggested params.
- `GET /api/v1/agents/improvements/metrics` aggregates.

## Human check
- Suggestions are advisory. Inspect before applying; `apply` only marks the record.
- A suggestion that lowers a safety threshold must be rejected (current code suggests
  `min_consensus_confidence: 75`).

## Change impact
- Change a metric → `agents/improvement.py` + `tests/test_improvement.py` + the API type.
- Persist history → ADR-005 style repository; update this card and the API.
- Add a reflection field → `agents/state.py`, journal/reflection agents, frontend type.

## Tests
`tests/test_reflection_agent.py`, `tests/test_improvement.py`, `tests/test_memory_agent.py`,
`tests/test_journal_agent.py`.

## Known gaps
History is in-memory and lost on restart; “win_rate” actually measures execution rate;
no link from a suggestion to the parameter it would change.
