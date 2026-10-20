<!-- docs/05-NEXT.md -->
# Next — prioritized plan

Derived from `02-STATUS.md`. Each phase has an exit criterion that can be tested.
Do not start a phase before the previous exit criterion is met unless a human says so.

## Phase 0 — capital safety (block release)

Completed 2026-10-21: **0.1 auth**, **0.2 one live-order path + fail-closed kill switch**,
**0.3 validated roster + universal fallback**, **0.4 realistic paper accounting**, and
**0.5 production config enforcement**. Phase 0 is closed; the remaining release risk is
Phase 1 (durability/one source of truth).

| # | Work | Files | Exit criterion | State |
|---|---|---|---|---|
| 0.1 | Auth on every non-public route + frontend session/API-key flow | `backend/core/dependencies.py`, `backend/main.py`, `backend/routers/**`, `frontend/src/lib/api.ts`, `frontend/src/components/AuthGate.tsx`, `frontend/src/app/login/page.tsx` | Route test enumerates `/api/v1` and fails on any unprotected path; UI sends the header; default/empty key returns 503 | **Done** |
| 0.2 | One fail-closed kill switch across API and runner; route all live orders through `execute_signal` | `live_trading/safety.py`, `live_trading/engine.py`, `agents/execution.py`, `scripts/run_live.py`, `backend/routers/live.py` | Integration test: Redis down → rejected; recovery still requires human re-arm; agent never calls `exchange.create_order` | **Done** |
| 0.3 | Refresh model roster + universal fallback | `configs/models.yaml`, `agents/models.py` | Every configured ID resolves in the live free catalog; exhausted chain reaches `openrouter/free` | **Done (manual catalog check)**; CI check remains |
| 0.4 | Realistic paper accounting: fees, slippage, mark-to-market, short proceeds | `paper_trading/engine.py`, `paper_trading/worker.py`, `agents/execution.py`, `configs/settings.py`, `backend/routers/trading.py` | Tests for fee-adjusted fill, intra-trade drawdown, and a profitable short; agent persists actual fill/quantity | **Done** |
| 0.5 | Enforce production config | `docker-compose.prod.yml`, `docker/docker-compose.prod.yml`, `configs/settings.py`, `.env.example` | Compose overlay sets `ENVIRONMENT=production`; validator rejects default API/JWT/DB secrets | **Done** |

## Phase 1 — one source of truth

- Persist portfolio/positions/orders; single repository used by API, worker, and runner (ADR-005).
- Add a `positions.side` column and make the DB ledger the durable source; the engine is
  still in-memory and the worker's portfolio row is only a projection today.
- Order idempotency (client order ID) and exchange reconciliation; implement `get_open_orders`.
- `/health` returns 503 when degraded; compose healthchecks use it.
- Real `/api/v1/metrics` from Prometheus counters, not `_last_state`.
- Track `migrations/versions/`, collapse the two Alembic heads, delete the duplicate SQL schema.
**Exit:** restart the stack mid-trade; portfolio, open positions, and promotion record are identical before and after.

## Phase 2 — product realism and UI

**Data and trust**
- `markets/page.tsx`: replace `Math.random()` candles (`:74-124`) with a real candles
  endpoint; stop auto-running analysis on mount/symbol change (`:26-29`) — make it an
  explicit action; dispose the chart on unmount (`chart.remove()`); guard concurrent runs.
- `settings/page.tsx`: persist through the API (save is a `setTimeout` today, `:74-80`);
  fix the displayed API URL `localhost:8080` vs client `8000` (`:170`); align
  `max_position_size` 10% with the backend 2% (`:22`); remove the fake secret preview.
- `live/page.tsx`: fetch status and audit with `Promise.all` (`:28-31`); pause polling
  when the tab is hidden; add an in-flight guard.

**React and accessibility**
- `usePipelinePolling.ts`: in-flight guard in `runAnalysis`, one poll at a time, abort on
  unmount, backoff on errors (`:35-91`).
- `api.ts`: request timeout/abort and typed errors; the auth header and 401
  redirect are already in place (`frontend/src/lib/auth.ts`, `AuthGate.tsx`).
- Accessibility: label the symbol `<select>`, connect settings labels with `htmlFor`,
  make toggles `role="switch"` with `aria-checked`, add `aria-live` for run/error state,
  a skip link, and raise contrast for `#52525b`/`#71717a` small text.
- Functional strategy builder and a real chat interface.
- Frontend lint/typecheck/test job in CI.
**Exit:** no page renders invented data; settings round-trip through the API; axe/Lighthouse pass.

## Phase 3 — hygiene

- Fix the mypy errors (all in tests/scripts); keep CI green.
- Re-verify README numbers (1044 / 79.08%) and roadmap status.
- Improvement engine: persist history, rename “win rate”, remove the 75% consensus suggestion.
- Add Prometheus alert rules; remove duplicate monitoring configs.
- Prune stale branches and land Dependabot PRs.

## Guardrails

- No phase may weaken a safety gate (see `01-SPEC.md`).
- Every change updates `02-STATUS.md` and the routed `CONTEXT.md` if the folder’s job changed.
- Code moves are a separate, explicitly approved change (ADR-002).
