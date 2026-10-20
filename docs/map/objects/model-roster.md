<!-- docs/map/objects/model-roster.md -->
# Model roster and fallback chain

**What it is:** the config-driven list of free-tier models per agent, plus the runtime
that walks the chain, retries, rate-limits, and trips circuit breakers.

**Homes:**
- `configs/models.yaml` — the **only** place model IDs exist.
- `agents/models.py` — loads/validates the roster (`AgentModelConfig`).
- `agents/router.py` — primary → fallback 1 → fallback 2, per-call result.
- `agents/circuit_breaker.py`, `agents/retry.py`, `agents/queue.py` — resilience.
- `agents/client.py` — HTTP client for OpenRouter/OpenCode.
- `agents/base.py` — converts router output into a typed agent output.

**Shape:** per agent `{primary, fallbacks[], timeout_seconds, max_retries}`; defaults for
timeout, retries, breaker threshold/reset, RPM, and `universal_fallback`.

**Writers:** humans edit YAML. The breaker/queue keep per-process state.

**Readers:** every LLM-backed agent, `scripts/run_live.py`, `backend/routers/analysis.py`.

**Invariants:**
- No model ID in source (hard rule #1).
- A failed required agent causes rejection, never approval.
- `AgentModelConfig.model_chain` appends `defaults.universal_fallback`
  (`open_router/openrouter/free`) last, deduplicated.
- Every fallback used is logged and counted (`AGENTS_FALLBACK_TOTAL`).

**Change impact:**
- Swap a model → YAML only; run the live-catalog check before merging.
- Change retry/breaker → `agents/retry.py`, `circuit_breaker.py`, and their tests.
- Add a provider → `agents/client.py` provider map + env var + `.env.example`.

**Tests:** `tests/test_router.py`, `test_retry.py`, `test_circuit_breaker.py`,
`test_queue.py`, `test_models.py`, `tests/test_test_free_models.py`.

**Known gaps:** catalog removals are not yet checked in CI. The roster was validated
against the live OpenRouter catalog on 2026-10-21 (14 unique free models, all
present). Rule-based fallbacks still hide model failures; the universal fallback
only guarantees one last model attempt.
