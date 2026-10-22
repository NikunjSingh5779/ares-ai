<!-- docs/05-NEXT.md -->
# Next — prioritized plan

Derived from `02-STATUS.md`. Each phase has an exit criterion that can be tested.
Do not start a phase before the previous exit criterion is met unless a human says so.

## Phase 0 — capital safety (block release)

Completed 2026-10-21: **0.1 auth**, **0.2 one live-order path + fail-closed kill switch**,
**0.3 validated roster + universal fallback**, **0.4 realistic paper accounting**, and
**0.5 production config enforcement**. Phase 0 is closed. P1-A (durable paper ledger)
was committed as `9c16122` on 2026-10-21; P1-B (approved `/execute` plus client-order
idempotency) followed in the next commit, `feat(paper): require approved execution and
client order ids`. P1-C (paper writer serialization) is committed as `fix(paper): serialize
ledger writers with an advisory lock`. P1.4 (real-PostgreSQL integration job) is committed
as `test(paper): run the ledger suite against real PostgreSQL in CI`; the job passed on its
first GitHub run (39601089127). P1.6 (role-based authorization) is committed locally and
verified, together with the mypy cleanup; neither is pushed yet. P1.5 (degraded health plus
Prometheus-backed metrics) is implemented and verified locally but remains uncommitted.
The Phase 1 Compose exit was run successfully on 2026-10-21 (portfolio, positions, orders,
and promotion record identical across a full-stack restart). The remaining release action
is committing and pushing P1.5 plus the Compose bootstrap fixes.

| # | Work | Files | Exit criterion | State |
|---|---|---|---|---|
| 0.1 | Auth on every non-public route + frontend session/API-key flow | `backend/core/dependencies.py`, `backend/main.py`, `backend/routers/**`, `frontend/src/lib/api.ts`, `frontend/src/components/AuthGate.tsx`, `frontend/src/app/login/page.tsx` | Route test enumerates `/api/v1` and fails on any unprotected path; UI sends the header; default/empty key returns 503 | **Done** |
| 0.2 | One fail-closed kill switch across API and runner; route all live orders through `execute_signal` | `live_trading/safety.py`, `live_trading/engine.py`, `agents/execution.py`, `scripts/run_live.py`, `backend/routers/live.py` | Integration test: Redis down → rejected; recovery still requires human re-arm; agent never calls `exchange.create_order` | **Done** |
| 0.3 | Refresh model roster + universal fallback | `configs/models.yaml`, `agents/models.py` | Every configured ID resolves in the live free catalog; exhausted chain reaches `openrouter/free` | **Done (manual catalog check)**; CI check remains |
| 0.4 | Realistic paper accounting: fees, slippage, mark-to-market, short proceeds | `paper_trading/engine.py`, `paper_trading/worker.py`, `agents/execution.py`, `configs/settings.py`, `backend/routers/trading.py` | Tests for fee-adjusted fill, intra-trade drawdown, and a profitable short; agent persists actual fill/quantity | **Done** |
| 0.5 | Enforce production config | `docker-compose.prod.yml`, `docker/docker-compose.prod.yml`, `configs/settings.py`, `.env.example` | Compose overlay sets `ENVIRONMENT=production`; validator rejects default API/JWT/DB secrets | **Done** |

## Phase 1 — one source of truth

P1-A completed 2026-10-21 and is committed as `9c16122`: PostgreSQL is the durable paper
ledger (`paper_trading/repository.py`), `PaperTradingLedger` coordinates the cache, and
the API, worker, and runner all use it. `positions.side`, cost, margin, and the equity
curve are persisted; `migrations/versions/` is tracked with one head. A restart-mid-trade
test and a manual PostgreSQL 16 round-trip pass.

P1-B is committed (`feat(paper): require approved execution and client order ids`):
`/execute` requires typed Market Analyst/Quant/Risk
approvals, the server re-runs consensus and derives price/size, and `client_order_id`
rejects duplicates with **409**. Tests and a real-PostgreSQL duplicate/restart check pass.

P1-C is committed (`fix(paper): serialize ledger writers with an advisory lock`): paper
writes take an in-process cache lock and a transaction-scoped PostgreSQL advisory lock
across hydrate → mutate → persist, so API, worker, and runner cannot lose each other's
updates. A writer that cannot get the lock within 10 s fails closed with **503**.

The Phase 1 exit was run on 2026-10-21 against the full `docker/docker-compose.yml` stack:
two concurrent approved fills persisted, all seven services restarted, and portfolio,
positions, orders, and the promotion record matched exactly before and after. A duplicate
`client_order_id` still returned **409** after the restart. Details and the startup fixes
are in `02-STATUS.md`.

| # | Work | Files | Exit criterion | State |
|---|---|---|---|---|
| 1.1 | Durable paper ledger, hydration, atomic persistence | `paper_trading/repository.py`, `paper_trading/ledger.py`, `paper_trading/engine.py`, `paper_trading/worker.py`, `backend/routers/trading.py`, `scripts/run_live.py`, schema/migrations | Restart preserves portfolio, positions, trades, and equity; failed writes restore the cache | **Done (P1-A)** |
| 1.2 | Secure `/execute`: require an approved signal/risk payload or explicitly mark manual paper trades | `backend/routers/trading.py`, `agents/execution.py`, schemas | A request without approval cannot create a position; manual trades are labeled/excluded from promotion | **Done (P1-B, approved-only; no manual path)** |
| 1.3 | Order idempotency + concurrent-writer safety | ledger/repository, order schema | Duplicate client order IDs are rejected; row locking or optimistic versions prevent lost updates across API/worker/runner | **Done (P1-B duplicates, P1-C writer lock)** |
| 1.4 | PostgreSQL integration test in CI | `tests/`, CI workflow | Testcontainers/Compose runs hydrate → fill → restart → close on a real database | **Done (P1.4)**; `postgres-integration` job |
| 1.5 | `/health` returns 503 when degraded; real Prometheus metrics | `backend/main.py`, `backend/core/metrics.py` | Compose healthchecks use the enriched health signal; `/api/v1/metrics` no longer reads `_last_state` | **Done (P1.5, local, uncommitted)** |
| 1.6 | Role-based authorization for trading/live controls | auth/JWT/API-key mapping, route tests | Viewer cannot trade; operator/admin required for live start/kill/arm/mode changes | **Done (P1.6, committed locally)** |
| 1.E | Compose mid-trade restart exit | `docker/docker-compose.yml`, `docker/backend-entrypoint.sh`, `.gitattributes` | Portfolio, positions, orders, and promotion record identical after a full-stack restart; concurrent fills survive; duplicate IDs still 409 | **Done (2026-10-21)** |

**Exit: met on 2026-10-21.** The full Compose stack was restarted with two open paper
positions. The post-restart JSON matched the pre-restart snapshot for portfolio, positions,
orders, and promotion record; both concurrent fills were present; a duplicate
`client_order_id` returned **409** without changing state. The test used synthetic symbols
so the background paper worker could not mark or stop the positions during the restart;
the `/execute` approval path and PostgreSQL ledger were the real ones. Startup also needed
the LF entrypoint fix, container-internal service hosts, a `0001` stamp when `init.sql`
pre-created the schema, and a Chroma server version/persistence path compatible with the
Python client.

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

- Keep `mypy .` green (clean on 184 files as of 2026-10-21; the 22 errors are fixed).
- Re-verify README numbers (1129 / 80.29%) and roadmap status.
- Improvement engine: persist history, rename “win rate”, remove the 75% consensus suggestion.
- Add Prometheus alert rules; remove duplicate monitoring configs.
- Prune stale branches and land Dependabot PRs.

## Guardrails

- No phase may weaken a safety gate (see `01-SPEC.md`).
- Every change updates `02-STATUS.md` and the routed `CONTEXT.md` if the folder’s job changed.
- Code moves are a separate, explicitly approved change (ADR-002).
