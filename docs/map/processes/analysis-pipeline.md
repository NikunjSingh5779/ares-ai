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
  → Execution (paper or live) — skipped when `execute_trades` is false
  → Journal (persist outcome + lessons)
  → Reflection (evaluate prediction vs outcome)
  → Memory (Chroma/in-memory recall + consolidation)
  → post-run hook: persist reflection, analyze cross-run trends (best-effort)
```

Consensus and Risk are **gates, not advisers**: if either rejects, execution is skipped
and the outcome is recorded as no-trade.

## Inputs
- `symbol`, `request`, optional `candles`; otherwise `MarketDataIngestor` fetches Yahoo/Binance.
- Current portfolio/risk limits from settings and the engine.

## Outputs
- `AgentState` with every node’s typed output.
- Paper/live trade row (via Execution + Journal) when approved.
- `POST /signal` with `execute=false` returns the typed approval and a short-lived
  signed `approval_token` for `/execute` instead of placing the trade; the graph stops
  after risk. Rejected or flat signals return no token.
- `reflection_runs` + advisory `improvement_records` when the post-run hook succeeds;
  a failure is logged and does not change the result.
- A bounded per-session `AnalysisStateStore` in the API process
  (`backend/services/analysis_control.py`), read by `/agents/status` (latest
  started run, or `?session_id=...`) and `/risk` (not by `/api/v1/metrics`,
  which reads the Prometheus registry).

## Human check
- `GET /api/v1/agents/status` shows completed/failed/skipped nodes and model chains.
- `GET /api/v1/agents/status?session_id=...` shows the run returned by
  `POST /api/v1/analyze`.
- A rejected trade must show a reason in `consensus.rationale` or `risk.reasons`.

## Change impact
- Add/reorder a node → `PIPELINE_ORDER`, graph edges, `REQUIRED_AGENTS`, status UI, this card.
- Change a threshold → `agents/consensus.py` / `agents/risk.py` + boundary tests.
- Change the entry route → `backend/routers/analysis.py`, `frontend/src/lib/api.ts`, types.
- Change concurrency, budget, deadline, or state retention →
  `backend/services/analysis_control.py`, `configs/settings.py`, `.env.example`,
  `tests/test_analysis_control.py`, `tests/test_analysis_router.py`,
  `tests/test_supervisor.py`, this card.
- Change the deadline check or execution clearing → `agents/supervisor.py`,
  `agents/state.py`, `tests/test_supervisor.py`, this card.
- Change approval-only mode or token issuance → `agents/state.py`,
  `agents/supervisor.py`, `backend/core/security.py`, `backend/routers/analysis.py`,
  `backend/routers/trading.py`, `tests/test_analysis_router.py`,
  `tests/test_security/test_approval_token.py`, ADR-025, this card.
- Change the post-run hook → `agents/supervisor.py`, `backend/services/improvement_service.py`,
  `scripts/run_live.py`, `tests/test_supervisor.py`, `tests/test_improvement_service.py`.

## Tests
`tests/test_supervisor.py`, `test_consensus.py`, `test_risk.py`,
`tests/test_analysis_control.py`, `tests/test_analysis_router.py`, `tests/test_agents/*`.

## Known gaps
- The gate and state store are process-local; a multi-worker API would need shared
  state (for example Redis) for the concurrency limit, run budget, and per-session
  reads. Compose runs one uvicorn worker.
- The run budget resets on process restart.
- LLM degradation is not surfaced in `degraded`.
