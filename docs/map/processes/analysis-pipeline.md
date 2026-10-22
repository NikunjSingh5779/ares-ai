<!-- docs/map/processes/analysis-pipeline.md -->
# Analysis pipeline

**Trigger:** `POST /api/v1/analyze`, `GET /api/v1/analyze/stream` (SSE),
`POST /api/v1/signal`, or the runner’s candle-close loop.

**Owner:** `backend/routers/analysis.py` (entry) → `agents/supervisor.py` (graph).

## Flow

```
request
  → Supervisor node (prepare state, fetch candles via backend/data/ingestor.py)
  → fan-out: Market Analyst │ Quant │ News │ Vision   (parallel)
  → Consensus (deterministic: both >80% and same non-flat direction)
  → Risk (deterministic + optional LLM, portfolio/drawdown checks)
  → Execution (paper or live)
  → Journal (persist outcome + lessons)
  → Reflection (evaluate prediction vs outcome)
  → Memory (Chroma/in-memory recall + consolidation)
  → Improvement (cross-run trend analysis, after memory)
```

Consensus and Risk are **gates, not advisers**: if either rejects, execution is skipped
and the outcome is recorded as no-trade.

## Inputs
- `symbol`, `request`, optional `candles`; otherwise `MarketDataIngestor` fetches Yahoo/Binance.
- Current portfolio/risk limits from settings and the engine.

## Outputs
- `AgentState` with every node’s typed output.
- Paper/live trade row (via Execution + Journal) when approved.
- `_last_state` in the API process, read by `/agents/status` and `/risk` (not by
  `/api/v1/metrics`, which reads the Prometheus registry).

## Human check
- `GET /api/v1/agents/status` shows completed/failed/skipped nodes and model chains.
- A rejected trade must show a reason in `consensus.rationale` or `risk.reasons`.

## Change impact
- Add/reorder a node → `PIPELINE_ORDER`, graph edges, `REQUIRED_AGENTS`, status UI, this card.
- Change a threshold → `agents/consensus.py` / `agents/risk.py` + boundary tests.
- Change the entry route → `backend/routers/analysis.py`, `frontend/src/lib/api.ts`, types.

## Tests
`tests/test_supervisor.py`, `test_consensus.py`, `test_risk.py`,
`tests/test_analysis_router.py`, `tests/test_agents/*`.

## Known gaps
- `_last_state` is a single module global: concurrent runs race (P1-7). `/agents/status`
  and `/risk` still read it; `/api/v1/metrics` does not.
- Unbounded background tasks; no per-user isolation or cost cap.
- LLM degradation is not surfaced in `degraded`.
