<!-- agents/CONTEXT.md -->
# agents/ — contract

**Purpose:** turn market data into typed decisions. LLM agents interpret; deterministic
modules gate. This is the controller + model layer of the pipeline.

## Layout
- `supervisor.py` — LangGraph wiring, node execution, error routing (entry point).
- `base.py` — `BaseAgent`, `AgentContext`, typed I/O validation.
- `state.py` — `AgentState` and every agent output schema (the models).
- `router.py`, `client.py`, `retry.py`, `queue.py`, `circuit_breaker.py` — model execution.
- `local_gate.py` — process-wide semaphore for the opt-in `local/` provider.
- Agents: `market_analyst`, `quant`, `news`, `vision`, `risk`, `execution`, `journal`,
  `reflection`, `memory`, `kronos_predictor`.
- Deterministic gates: `consensus.py`; rules in `risk.py`, `indicators.py`, `candlesticks.py`.
- `improvement.py` — cross-run analysis; accepts an explicit history window and emits
  UUID-tagged advisory records. `web_collector.py` — research input.

## Inputs
`AgentState` slices (symbol, request, candles) and market data from `backend/data/`.

## Process
1. Supervisor prepares state and fans out to analysts.
2. Each LLM agent builds a prompt, calls `ModelRouter`, parses JSON into its output schema,
   falls back to the rule-based result on failure, and records `used_fallback`.
3. Consensus and Risk are deterministic nodes — they never call an LLM.
4. Execution delegates to `paper_trading/` or `live_trading/`; Journal/Reflection/Memory persist.
5. After the graph, the optional supervisor `post_run_hook` persists the reflection run and
   runs improvement analysis against committed history. It is best-effort: a failure is
   logged and never changes the pipeline result.

## Outputs
Validated Pydantic outputs merged into `AgentState`; trade rows via Journal/Memory.
Also emits `AGENTS_RUNS_TOTAL` / `AGENTS_FALLBACK_TOTAL` metrics.

## Invariants
- Model IDs only in `configs/models.yaml`; the configured universal fallback is appended.
- The `local/` provider is opt-in, chat-first, and gated process-wide (default one
  concurrent request). A busy local gate skips that model without tripping its breaker.
- `rationale` required on every trading-relevant output.
- A failed required agent rejects; never approve by default.
- No exchange or DB access from analyst agents; only Execution/Journal/Memory touch state.
- `ExecutionAgent` routes live orders through `LiveTradingEngine.execute_signal`; it
  never calls the exchange directly.
- Improvement records are advisory. Applying one marks operator review; it never mutates
  a threshold, position cap, promotion gate, or the kill switch.
- `analyze(history=...)` must not mutate process globals; the persistence service owns
  the committed history and passes an explicit window.

## Human check
`GET /api/v1/agents/status` — completed/failed nodes, model chains, `degraded`.

## Tests
`tests/test_supervisor.py`, `test_consensus.py`, `test_risk.py`, `test_quant.py`,
`test_market_analyst.py`, `test_agents/*`, `test_improvement.py`, `test_memory_agent.py`,
`test_local_gate.py`, `test_client.py`, `test_router.py`.

## Known gaps
LLM degradation is silent (rule fallback looks healthy) and there is no corrective
schema retry. Catalog removals are not yet checked in CI. The local provider is wired
for chat only; pipeline-local use remains opt-in work until schema compliance and
latency are measured. Improvement suggestions are not linked to the exact config field
they would change, so an operator must map a suggestion to a parameter manually.
