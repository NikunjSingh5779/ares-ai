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
as `test(paper): run the ledger suite against real PostgreSQL in CI`. P1.6 (role-based
authorization), the mypy cleanup, P1.5 (degraded health plus Prometheus-backed metrics), and
the Compose bootstrap fixes are committed and pushed at `34ff7b8`; docs reconciliation
`0d55263`, the handoff refresh `e406d5d`, and the conventional docs set are on top. The
Phase 1 Compose exit
was run successfully on 2026-10-21 (portfolio, positions, orders, and promotion record
identical across a full-stack restart). The Phase 2 slices through `88bdfef` passed
GitHub Actions run **39780873063** (feature slices) and **39785044719** (frontend CI)
on all five jobs: `lint`, `test`, `postgres-integration`, `frontend`, and `docker`;
the docs correction `8fb7c5b` passed run **39786478379**. The sixth Phase 2 slice
(read-only multi-turn chat) is verified and recorded in `02-STATUS.md`. Phase 1 is
closed.

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
| 1.5 | `/health` returns 503 when degraded; real Prometheus metrics | `backend/main.py`, `backend/core/metrics.py` | Compose healthchecks use the enriched health signal; `/api/v1/metrics` no longer reads `_last_state` | **Done (P1.5, committed and pushed)** |
| 1.6 | Role-based authorization for trading/live controls | auth/JWT/API-key mapping, route tests | Viewer cannot trade; operator/admin required for live start/kill/arm/mode changes | **Done (P1.6, committed and pushed)** |
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
- `markets/page.tsx`: **done 2026-10-22** — real candles from
  `GET /api/v1/market/candles`, explicit **Analyze** action (no mount/symbol
  auto-run), `chart.remove()` on unmount, and a concurrent-run guard.
- `settings/page.tsx`: **done 2026-10-22** — loads and saves through
  `GET/PUT /api/v1/settings`; preferences live in the singleton `app_settings` row.
  Safety limits are read-only from the enforcing constants, including the **2%**
  position cap; the API URL comes from `NEXT_PUBLIC_API_URL`; no fake token or
  WebSocket preview remains; labels and `aria-live`/`role="alert"` are in place.
- `live/page.tsx`: **done 2026-10-22** — status and audit load concurrently with
  `Promise.all`; polling pauses while the tab is hidden and resumes on visibility;
  refreshes are single-flight and abort on unmount; control actions force a fresh
  read so stale polls cannot overwrite them. The interval comes from the saved
  `live_refresh_seconds` preference.

**React and accessibility**
- `usePipelinePolling.ts`: **done 2026-10-22** — polling starts after `POST /analyze`
  is accepted, one status request at a time, abort on unmount, and 1/2/4/8 s backoff
  under the 60 s safety timeout. `runAnalysis` rejects concurrent triggers.
- `api.ts`: **done 2026-10-22** — bounded request timeouts, caller `AbortSignal`
  support, and typed `ApiError`/`ApiTimeoutError`; the auth header and 401 redirect
  remain in place.
- Accessibility: **done 2026-10-24** — skip link to `#main-content`, sidebar
  `aria-label`/`aria-current`, labelled live controls, dialog roles/labels/Escape/
  initial focus, strategy-builder labels and `aria-pressed`, and muted-text contrast
  raised to `#8b8b93`/`#a1a1aa`. Lighthouse 13.5.0 scored **100** on `/login` and
  axe-core 4.14.0 reported **0 violations across 16 authenticated route shells**;
  the audit also fixed active-nav contrast, the market chart role, `/live`
  loading/error headings, `/backtests` labels, and chat-log keyboard access.
- Strategy builder: **done 2026-10-22** — drafts persist through
  `GET/POST/PUT /api/v1/strategies`; status, live enablement, and promotion fields
  stay server-owned; the form loads saved drafts and hands supported types to the
  backtest page. A mock-session test suite covers create/list/get/update and the
  404/409/422/503 boundaries.
- Chat: **done 2026-10-22; local fallback 2026-10-24** — `POST /api/v1/chat` sends a
  bounded (1–20 turn) history through a free-tier fallback chain and returns the reply
  plus the model/fallback metadata. The page keeps multi-turn state and sends prior
  turns; the service has no tools and cannot place orders, change modes, promote
  strategies, or bypass a safety gate. A `chat` entry in `configs/models.yaml` holds
  the remote IDs; the separate opt-in `local_chat` entry is appended when enabled or
  used alone when no remote key exists.
- Frontend lint/typecheck/test: **done 2026-10-22** — ESLint 9 flat config
  (`eslint . --max-warnings=0`), `tsc --noEmit`, and Vitest 5 + Testing Library
  (**18 tests**) run in the `frontend` CI job before `pnpm build`.
**Exit:** no page renders invented data; settings round-trip through the API (met
2026-10-22); live/pipeline polling is bounded and pause-aware (met 2026-10-22);
strategy drafts round-trip through the API (met 2026-10-22); chat is multi-turn and
read-only (met 2026-10-22); frontend lint, typecheck, and tests run in CI (met
2026-10-22); axe/Lighthouse pass met 2026-10-24 for the login page and the
authenticated route shells; data-populated states remain an optional follow-up.

**Phase 2 is closed as of 2026-10-24.**

## Phase 3 — hygiene

- Keep `mypy .` green (clean on 211 files as of 2026-10-24).
- Keep verified numbers out of README; it points at `02-STATUS.md` as the single
  source of truth. Re-check roadmap status when a slice lands.
- Improvement engine: **metric rename and unsafe suggestion removed 2026-10-24;
  durable history and pipeline wiring landed 2026-10-24.** `win_rate` is now
  `execution_rate` (it measured executed/total), and the decline record no longer
  proposes lowering consensus confidence to 75%. `reflection_runs` and
  `improvement_records` (migration `0006`) persist history; a best-effort post-run
  hook analyzes it after every `/analyze` and live-runner pipeline pass. Remaining:
  suggestions are not linked to the exact config field they would change.
- Add Prometheus alert rules; remove duplicate monitoring configs.
- Prune stale branches and land Dependabot PRs.

## Guardrails

- No phase may weaken a safety gate (see `01-SPEC.md`).
- Every change updates `02-STATUS.md` and the routed `CONTEXT.md` if the folder’s job changed.
- Code moves are a separate, explicitly approved change (ADR-002).
