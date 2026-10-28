<!-- docs/map/objects/agent-state.md -->
# AgentState

**What it is:** the single typed state object threaded through the LangGraph pipeline.
Each node reads its input slice and returns a validated output that is merged back.

**Home:** `agents/state.py` — `AgentState`, `PipelineStatus`, and one output model per agent.

**Shape (top level):**
- Input: `request_id`, `session_id`, `symbol`, `request`, `request_type`, `execute_trades`,
  `candles`
- Outputs: `market_analyst`, `quant`, `news`, `vision`, `consensus`, `risk`, `execution`,
  `journal`, `reflection`, `memory`, `kronos`
- Metadata: `pipeline_status`, `errors`, `model_chain_used`, `degraded`,
  `total_latency_ms`, `agent_latencies`, `rolling_memory`

**Writers:** every node in `agents/supervisor.py`; parallel branches merge via
`pipeline_status` and list/dict reducers.

**Readers:** downstream nodes, `backend/routers/analysis.py` (stores the last state),
`backend/routers/agents.py` (status) and `monitoring.py` (`/risk`) read it back.
`/api/v1/metrics` does not; it reads the Prometheus registry.

**Invariants:**
- Every output model requires `rationale` (except `KronosOutput`, which defaults it).
- Confidence is bounded 0–100; direction is `long|short|flat`.
- A missing required output (`market_analyst`, `quant`, `consensus`, `risk`) means no trade.

**Change impact:**
- Add/rename a field → update every reader in `agents/supervisor.py`, the frontend
  `AgentStatusResponse` type, and the node tests.
- Change a threshold → `agents/consensus.py` plus its boundary tests.
- Add a new agent → `PIPELINE_ORDER`, the graph edges, `REQUIRED_AGENTS` if blocking,
  and `docs/map/processes/analysis-pipeline.md`.

**Tests:** `tests/test_schema.py`, `tests/test_supervisor.py`, `tests/test_consensus.py`.

**Known gap:** `used_fallback` on Quant/Market Analyst is not propagated into
`AgentState.degraded`, so a rule-based run can look healthy (also noted in
`agents/CONTEXT.md`).
