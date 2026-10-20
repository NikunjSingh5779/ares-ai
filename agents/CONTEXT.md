<!-- agents/CONTEXT.md -->
# agents/ — contract

**Purpose:** turn market data into typed decisions. LLM agents interpret; deterministic
modules gate. This is the controller + model layer of the pipeline.

## Layout
- `supervisor.py` — LangGraph wiring, node execution, error routing (entry point).
- `base.py` — `BaseAgent`, `AgentContext`, typed I/O validation.
- `state.py` — `AgentState` and every agent output schema (the models).
- `router.py`, `client.py`, `retry.py`, `queue.py`, `circuit_breaker.py` — model execution.
- Agents: `market_analyst`, `quant`, `news`, `vision`, `risk`, `execution`, `journal`,
  `reflection`, `memory`, `kronos_predictor`.
- Deterministic gates: `consensus.py`; rules in `risk.py`, `indicators.py`, `candlesticks.py`.
- `improvement.py` — cross-run analysis. `web_collector.py` — research input.

## Inputs
`AgentState` slices (symbol, request, candles) and market data from `backend/data/`.

## Process
1. Supervisor prepares state and fans out to analysts.
2. Each LLM agent builds a prompt, calls `ModelRouter`, parses JSON into its output schema,
   falls back to the rule-based result on failure, and records `used_fallback`.
3. Consensus and Risk are deterministic nodes — they never call an LLM.
4. Execution delegates to `paper_trading/` or `live_trading/`; Journal/Reflection/Memory persist.

## Outputs
Validated Pydantic outputs merged into `AgentState`; trade rows via Journal/Memory.
Also emits `AGENTS_RUNS_TOTAL` / `AGENTS_FALLBACK_TOTAL` metrics.

## Invariants
- Model IDs only in `configs/models.yaml`; the configured universal fallback is appended.
- `rationale` required on every trading-relevant output.
- A failed required agent rejects; never approve by default.
- No exchange or DB access from analyst agents; only Execution/Journal/Memory touch state.
- `ExecutionAgent` routes live orders through `LiveTradingEngine.execute_signal`; it
  never calls the exchange directly.

## Human check
`GET /api/v1/agents/status` — completed/failed nodes, model chains, `degraded`.

## Tests
`tests/test_supervisor.py`, `test_consensus.py`, `test_risk.py`, `test_quant.py`,
`test_market_analyst.py`, `test_agents/*`, `test_improvement.py`, `test_memory_agent.py`.

## Known gaps
LLM degradation is silent (rule fallback looks healthy) and there is no corrective
schema retry. Catalog removals are not yet checked in CI.
