<!-- docs/map/objects/model-roster.md -->
# Model roster and fallback chain

**What it is:** the config-driven list of free-tier remote models per agent, plus the
opt-in local chat fallback and the runtime that walks the chain, retries, rate-limits,
gates local concurrency, and trips circuit breakers.

**Homes:**
- `configs/models.yaml` — the **only** place model IDs exist.
- `agents/models.py` — loads/validates the roster (`AgentModelConfig`).
- `agents/router.py` — primary → fallback 1 → fallback 2, per-call result.
- `agents/circuit_breaker.py`, `agents/retry.py`, `agents/queue.py` — resilience.
- `agents/client.py` — HTTP client for OpenRouter/OpenCode and the `local/` provider.
- `agents/local_gate.py` — process-wide semaphore shared by every local-model router.
- `agents/base.py` — converts router output into a typed agent output.

**Shape:** per agent `{primary, fallbacks[], timeout_seconds, max_retries}`; defaults for
timeout, retries, breaker threshold/reset, RPM, and `universal_fallback`. The separate
`local_chat` entry uses `local/qwen3.6-35b-a3b-ud-q4_k_m`; it is not part of the
free-tier `chat` chain. The optional `web_collector` entry supplies the browser-use
agent's `ChatOpenRouter` model; that path uses the primary only and fails closed
rather than walking the router chain.

**Writers:** humans edit YAML. The breaker/queue and local gate keep per-process state.

**Readers:** every LLM-backed agent, `scripts/run_live.py`, `backend/routers/analysis.py`,
`agents/web_collector.py`, and `backend/services/chat_service.py`.

**Invariants:**
- No model ID in source (hard rule #1).
- A failed required agent causes rejection, never approval.
- Optional paths that build their own provider client (browser-use) must validate the
  roster ID with `agents/client.py::free_model_policy_violation` and set the same
  zero-price OpenRouter bound; they may not bypass the free-only policy.
- `AgentModelConfig.model_chain` appends `defaults.universal_fallback`
  (`open_router/openrouter/free`) last, deduplicated. The chat service uses the
  explicit local entry, not its universal fallback.
- Every fallback used is logged and counted (`AGENTS_FALLBACK_TOTAL`).
- The local model is single-request by default; acquisition is bounded, and a busy
  gate skips the model without recording a breaker failure.

**Change impact:**
- Swap a model → YAML only. `.github/workflows/model-catalog.yml` probes the live
  catalog weekly and on demand; run `scripts/test_free_models.py` locally before
  merging a roster change.
- Change retry/breaker → `agents/retry.py`, `circuit_breaker.py`, and their tests.
- Add a provider → `agents/client.py` provider map + env var + `.env.example`.
- Change local concurrency → `agents/local_gate.py` and `LOCAL_LLM_*` settings; keep
  Strata's `--parallel N` as a separate server-side choice.

**Tests:** `tests/test_router.py`, `test_retry.py`, `test_circuit_breaker.py`,
`test_queue.py`, `test_models.py`, `test_local_gate.py`, `test_client.py`,
`test_chat_service.py`, `test_web_collector.py`, `tests/test_test_free_models.py`,
and the workflow contract in `tests/test_infra_config.py`.

**Known gaps:** catalog removals are checked weekly by
`.github/workflows/model-catalog.yml` (requires the `OPENROUTER_API_KEY` repository
secret), but that job has not yet run on GitHub Actions. The roster was last
validated against the live OpenRouter catalog on 2026-10-21 (14 unique free models,
all present). Rule-based fallbacks still hide model failures; the universal fallback
only guarantees one last model attempt. The local model is chat-only for now; its
`qwen3.6-35b-a3b-ud-q4_k_m` ID was smoke-tested against a live Strata server on
2026-10-24.
