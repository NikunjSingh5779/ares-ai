<!-- docs/02-STATUS.md -->
# Status — verified state

**Last verified:** 2026-10-25
**Branch:** `fix/orchestration-reliability-frontend` — 31 commits ahead / 0 behind
`origin/master` after merge `67c5222`. Recent verified work adds the real-PostgreSQL
strategy route module, the opt-in local chat fallback, the accessibility audit, the improvement
metric correction, durable improvement history wired into the pipeline, and Prometheus
alert rules with one tracked monitoring set.
The phase-2 baseline `caae9d6` (`feat(phase-2): wire real market, settings, live, and
strategy data`) passed GitHub Actions run **39780873063** on all five jobs: `lint`,
`test`, `postgres-integration`, `frontend`, and `docker`.
P1-A is committed as `9c16122`; P1-B (approved-only `/execute` plus client-order
idempotency) is committed as `feat(paper): require approved execution and client order
ids`; P1-C (paper writer lock) is committed as `fix(paper): serialize ledger writers with
an advisory lock`; P1.4 (real-PostgreSQL integration job) is committed as
`test(paper): run the ledger suite against real PostgreSQL in CI`.
Earlier GitHub Actions runs **39742069953** (code), **39745749404** (docs), and
**39747241203** (handoff) also passed all five jobs.
The fifth Phase 2 slice — frontend lint, typecheck, tests, and their CI steps — is
committed as **`88bdfef`** and passed GitHub Actions run **39785044719**, including the
new lint, typecheck, test, and build steps. The docs correction `8fb7c5b` passed run
**39786478379**. The sixth Phase 2 slice — read-only multi-turn chat — is committed as
**`c3518e5`** and passed GitHub Actions run **39791860387** on all five jobs. The
improvement-history slice `c322f23` passed GitHub Actions run **40097868595** on all
five jobs, including `postgres-integration` with all three PostgreSQL modules. The local
`.env` key is unique (never committed), so authenticated `/api/v1/*` calls work locally.
**Method:** commands run locally against the working tree, not labels copied from earlier docs.

## Green

| Check | Command | Result |
|---|---|---|
| Test suite | `pytest tests/ -q` | **1259 passed, 3 skipped** (all three PostgreSQL integration modules skip without `ARES_TEST_POSTGRES_URL`) |
| Coverage | `pytest tests/ -q` | **82.17%** default (gate 78%); the ledger module adds 5 tests, the strategy module adds 12, and the improvement module adds 6 when the URL is set |
| Role authorization | `pytest tests/test_security/test_role_auth.py -q` | **18 passed** — viewer/operator/admin matrix, API-key mapping, missing/unknown role denial, real-route viewer 403s |
| Health and metrics | `pytest tests/test_monitoring -q` | **34 passed** — 503 on each degraded dependency, 200 only when all answer, Prometheus-backed JSON snapshot, `/metrics` exposition mount |
| Infra config | `pytest tests/test_infra_config.py -q` | **18 passed** — build args, container service hosts, Chroma pin, LF entrypoint, alert rules, single monitoring set, dashboard JSON |
| Type check | `mypy .` | **clean, 211 source files** |
| Structure | `pytest tests/test_icm_structure.py -q` | **20 passed** — contracts exist, entry file small, links resolve |
| Market candles | `pytest tests/test_market_router.py -q` | **13 passed** — validation, ordering, deduplication, 404/502/504, source selection |
| Settings | `pytest tests/test_settings_router.py tests/test_settings_service.py -q` | **23 passed** — GET/PUT round-trip, normalization, 422 on safety overrides, 503 when the store is unavailable |
| Strategy drafts | `pytest tests/test_strategy_router.py tests/test_strategy_service.py -q` | **29 passed** — create/list/get/update, JSON parsing, version bump, 404/409/422/503, and rejection of lifecycle/live fields; the real-PostgreSQL module adds 12 route/service cases |
| Improvement history | `pytest tests/test_improvement.py tests/test_improvement_service.py tests/test_agents_router.py -q` | **38 passed** — external-history analysis, UUID record IDs, commit/rollback, 503/404/422 API contract, and advisory apply |
| Supervisor hook | `pytest tests/test_supervisor.py -q` | **30 passed** — the optional post-run hook receives the final state and a hook failure leaves the pipeline result unchanged |
| Chat | `pytest tests/test_chat_router.py tests/test_chat_service.py -q` | **21 passed** — history bounds, last-user validation, system prompt, fallback metadata, error-envelope/empty checks, free-tier roster, cached service, remote-plus-local and local-only chain selection |
| Local model gate | `pytest tests/test_local_gate.py tests/test_client.py tests/test_router.py -q` | **27 passed** — process-wide serialization/timeout, prefix stripping, no auth header, `reasoning_effort="off"`, local timeout, busy skip without breaker failure |
| Lint | `ruff check .` | clean |
| Format | `ruff format --check .` | clean |
| PostgreSQL integration | `ARES_TEST_POSTGRES_URL=... pytest tests/test_postgres_integration.py tests/test_postgres_strategy_integration.py tests/test_postgres_improvement_integration.py -q` | **23 passed** — real hydrate → fill → restart → close, duplicate ID, concurrent fills, one-winner duplicate race, busy lock → retry, the strategy route → service → JSONB round-trip, and the reflection/improvement run → record → API round-trip |
| CI PostgreSQL job | GitHub Actions `CI` run 40097868595 | **passed** on `postgres:16-alpine` — all three modules, **23 tests**, no skip (5 ledger, 12 strategy, 6 improvement) |
| Paper-ledger tests | `pytest tests/test_paper_trading_ledger.py -q` | **34 passed** — hydration, atomic write, duplicate ID, writer lock, rejection/rollback, restart mid-trade |
| Trading-route tests | `pytest tests/test_trading_router.py -q` | **17 passed** — approval, derivation, 409/422/503, busy-lock retry |
| Schema tests | `pytest tests/test_schema.py -q` | **16 passed** — 21 tables, ledger/idempotency columns, app_settings, init/schema parity, migration splitter |
| Worker tests | `pytest tests/test_paper_trading_worker.py -q` | **13 passed** — ledger delegation, locked symbol hydration |
| Alembic | `python -m alembic heads` | **`0006_improvement_history (head)`** |
| PostgreSQL 16 P1-C check | temporary container: concurrent fills, duplicate client ID, held lock → 503-equivalent busy error, released lock retry, cancelled writer | passed; no leaked advisory locks; container and script removed |
| PostgreSQL 16 P1-B check | temporary container: fresh `upgrade head`, P1-A schema → `stamp 0002` → `upgrade head`, duplicate execute before/after restart | passed; container and temporary scripts removed |
| Frontend build | `pnpm build` (in `frontend/`) | passed (real candle chart on `/markets`; real settings read/write on `/settings`; bounded live/status polling plus skip-link/ARIA/contrast changes on `/live`; persisted draft save/load and backtest handoff on `/strategy-builder`; read-only multi-turn chat on `/chat`; Next 16.2.12) |
| Frontend lint | `pnpm lint` (in `frontend/`) | clean — ESLint 9 flat config with `eslint-config-next` core-web-vitals, `--max-warnings=0` |
| Frontend type check | `pnpm typecheck` (in `frontend/`) | clean — `tsc --noEmit` |
| Frontend tests | `pnpm test` (in `frontend/`) | **18 passed** in 4 files — API client, pipeline polling, auth gate, chat page (Vitest 5 + Testing Library + jsdom) |
| API ↔ frontend paths | `app.openapi()` vs `src/lib/api.ts` | every path resolves |

## P0 fixes landed (2026-10-21)

| Fix | Evidence |
|---|---|
| Auth on every non-public route | `backend/main.py` mounts every domain router with `Depends(verify_auth)`; `tests/test_security/test_route_auth.py` traverses FastAPI 0.139 `_IncludedRouter` wrappers and fails if any `/api/v1` route is unprotected (the old flat scan was vacuous on this FastAPI version). Default/empty `API_SECRET_KEY` returns 503; no `API_DEBUG` bypass. |
| Single-user registration, no role escalation | `/auth/register` is a one-time bootstrap that requires the operator's API key; the first account is admin and later registrations are 403. `UserRegister` has no `role` field. |
| Fail-closed, shared kill switch | `live_trading/safety.py` latches on `redis.RedisError`/`OSError`; `is_active`/`check()` return blocked; `arm()` refuses while Redis is down; after recovery a human `arm()` is required. `/live/kill` and `/live/arm` work with no exchange configured. |
| One live-order path | `agents/execution.py` calls `LiveTradingEngine.execute_signal()`; the only production `exchange.create_order` call site is `live_trading/engine.py`. Tests assert the agent never calls the exchange directly. |
| Paper-only by default | `settings.live_trading_enabled=False`; `/live/start`, `set_mode(auto\|semi)`, the agent, and the engine all refuse. Even when enabled, kill switch + mode + promotion + connection must pass. |
| Validated free roster + universal fallback | 14 unique OpenRouter free models checked against the live catalog on 2026-10-21; `defaults.universal_fallback: open_router/openrouter/free` is appended (deduplicated) by `AgentModelConfig.model_chain`. |
| Realistic paper fills and marks | `paper_trading/engine.py` applies configured commission/slippage, marks open positions with `mark_to_market`, and derives `total_pnl` from equity. The application engine wires 10 bps per side from `configs/settings.py`; direct test engines stay frictionless. |
| Correct short and fee accounting | Shorts credit proceeds, report 100% notional margin, and subtract the liability from equity. Closed trades carry entry/exit commissions; `tests/test_paper_trading.py::TestRealisticAccounting` covers fee-adjusted fills, intra-trade drawdown, and a profitable short. |
| Actual agent fill/size + promotion records | `agents/execution.py` reports/persists the engine's fill and quantity, maps long/short to `buy`/`sell` for `trade_history`, and `paper_trading/worker.py` marks each candle and inserts SL/TP closures so the promotion gate counts them. |
| Production overlay enforces secrets | `docker-compose.prod.yml` and `docker/docker-compose.prod.yml` set `ENVIRONMENT=production` for app services; the existing settings validator then refuses default API/JWT/DB secrets. Verified with `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` and `tests/test_config.py`. |
| Strict consensus threshold | `agents/consensus.py` now requires both Market Analyst and Quant confidence **strictly above** 80%, matching the spec; `tests/test_consensus.py::test_edge_confidence_exactly_80_is_rejected` locks the boundary. |

## P1-A — durable paper ledger (committed as `9c16122`, verified 2026-10-21)

| Piece | Evidence |
|---|---|
| PostgreSQL is the source of truth | `paper_trading/repository.py` reads/writes the paper account/portfolio, open positions, closed trades, orders, and equity curve. `PaperTradingEngine` is a hydrated calculation cache. |
| One service coordinates cache and ledger | `paper_trading/ledger.py` refreshes before every action, mutates the engine, writes one transaction, and restores the pre-action snapshot if the write fails or the signal is rejected. An accepted fill with no seeded account is rejected, not silently kept in memory. |
| API reads hydrate first | `/api/v1/portfolio`, `/positions`, and `/orders` refresh from the ledger; `PaperLedgerError` returns **503 Paper ledger unavailable**. `/execute` goes through the ledger and returns `ledger_persisted=true` on success. |
| Worker and runner use the ledger | `paper_trading/worker.py` and `scripts/run_live.py` process candles through `PaperTradingLedger.process_candle`, so marks, SL/TP closures, orders, and history are persisted together. |
| Schema and migrations are consistent | `database/schema.sql` and `database/init.sql` are byte-identical after line-ending normalization. `migrations/versions/` is tracked and contains `.gitkeep`, `0001_initial_schema.py`, `0002_paper_ledger.py`, and `0003_order_idempotency.py`; `alembic heads` reports one head. |
| Restart proof | `tests/test_paper_trading_ledger.py::test_restart_mid_trade_restores_position_and_closes_after_restart` plus a manual PostgreSQL 16 run: open long → restart/hydrate → stop-loss close → second restart preserved the closed trade and equity curve. The same real-DB check then opened a short, reversed it to long, and a third restart preserved one open long and two closed trade rows with correct `position_side`. |
| Schema additions | `positions.side`, `entry_commission`, `margin`; `portfolio.initial_capital`, `margin_used`, `equity_curve`; `trade_history.position_side`, `entry_commission`, `exit_commission`, `exit_reason`. |
| Migration repair | `0001` now splits comments and dollar-quoted PL/pgSQL correctly; `0002` is idempotent because `0001` executes the current schema. The duplicate ignored Alembic head `89145e7e47e6_initial_schema_migration.py` was removed. Real PostgreSQL check: old schema → `stamp 0001` → `upgrade head` backfilled a sell trade to `position_side='short'` and added the columns; fresh `upgrade head` also passed. |

P1-A closes the old “two portfolio sources” and “positions cannot represent shorts” gaps.
P1-C closes concurrent-writer safety; API, worker, and runner now serialize on an advisory
lock instead of overwriting each other.

## P1-B — approved execution + client-order idempotency (committed, verified 2026-10-21)

| Piece | Evidence |
|---|---|
| `/execute` requires upstream approval | `backend/schemas/trading.py::ExecuteTradeRequest` requires `client_order_id`, `symbol`, `side`, and a nested `approval` containing typed Market Analyst, Quant, and Risk outputs (optional Vision). The old raw `quantity`/`entry_price` body is rejected with 422. |
| Server re-runs the gate | `backend/routers/trading.py` calls `ConsensusEngine.evaluate` again, requires both confidence values >80 and matching directions, requires `risk.approved`, and rejects `risk_score > 70`. A caller-supplied approval boolean is never trusted. |
| Server derives the fill and size | Entry price comes from `market_analyst_output.indicators.current_price`; quantity comes from `risk_output.max_position_size`; stop-loss comes from `risk_output.stop_loss`. The route rejects non-finite values and a stop on the wrong side of the entry. |
| Exposure cap | Notional is capped at **2% of current paper equity** using `MAX_POSITION_SIZE_PCT`; the route rejects oversized payloads with 422. |
| No manual bypass | Manual paper trades are not accepted by `/execute`; generated trades continue through `/signal`. The manual-trade labeling/promotion-exclusion path was therefore not added. |
| Idempotency key | `client_order_id` is required and unique per paper account. `orders.client_order_id` plus partial unique index `uq_orders_client_order_id` is the race-free guard; the repository also pre-checks, and duplicates return **409 Conflict** without a second position. |
| Atomic failure behavior | A duplicate request never creates a second position. The pre-check happens before engine mutation; if the unique index catches a concurrent duplicate after mutation, the hydrated cache snapshot is restored. A persistence failure also restores it. |
| Migration | `migrations/versions/0003_order_idempotency.py` adds the column/index idempotently because fresh `0001` executes current `schema.sql`. `alembic heads` reports `0003_order_idempotency`. |
| Real PostgreSQL proof | Fresh `upgrade head` and P1-A schema → `stamp 0002_paper_ledger` → `upgrade head` both produced the column/index. A duplicate `client_order_id` was rejected before and after restart; exactly one order and one open position remained. |
| Frontend client | `frontend/src/lib/api.ts::executeTrade` now sends the approved-only shape. It remains unused by pages; no UI bypass exists. |

P1-B closes the raw-body `/execute` gap and the duplicate-order half of P1.3. P1-C closes
the lost-update half.

## P1-C — paper writer serialization (committed, verified 2026-10-21)

| Piece | Evidence |
|---|---|
| Cross-process lock | `paper_trading/repository.py::PaperLedgerRepository.writer_lock` acquires `pg_try_advisory_xact_lock` before hydration and holds it through `persist`; the transaction-scoped lock is released by the rollback on context exit. |
| Bounded wait | The lock is polled until `PAPER_TRADING_WRITER_LOCK_TIMEOUT_SECONDS` (default 10 s). A writer that cannot acquire it raises `PaperLedgerBusyError`; `/execute` returns **503** with `Retry-After: 1`, worker and runner log and retry next tick. |
| In-process lock | `PaperTradingLedger` wraps every cache read/write in an `asyncio.Lock`, so a reader cannot re-hydrate the shared engine between another handler's mutation and its commit. |
| Worker read path | `PaperTradingWorker` uses `PaperTradingLedger.get_open_position_symbols()` instead of refreshing then reading the engine directly. |
| Schema unchanged | No migration; `alembic heads` remains `0003_order_idempotency`. |
| Real PostgreSQL proof | Two concurrent fills on different symbols both persisted (2 positions, 2 orders, cash 78 000). Concurrent duplicate `client_order_id` → exactly one accepted, one `PaperOrderConflictError`, 1 order/1 position. A held advisory lock → `PaperLedgerBusyError` with no mutation; after release the retry succeeded. A cancelled writer released the lock (no advisory locks remained). |

P1-C closes the concurrent-writer gap for paper state. The lock is database-wide, not
per-account; that is acceptable at single-user scale. Reads do not take the advisory lock
because each process has its own cache. Role authorization is closed by P1.6; a signed
signal token (P2) remains open.

## P1.4 — real-PostgreSQL integration in CI (committed, verified 2026-10-21)

| Piece | Evidence |
|---|---|
| Opt-in tests | `tests/test_postgres_integration.py` runs only when `ARES_TEST_POSTGRES_URL` is set; otherwise the module skips, so the default suite needs no database. |
| Safety gate | The module refuses to run unless the target database name contains `test`; setup/teardown truncates only `users`, `accounts`, `portfolio`, `positions`, `orders`, and `trade_history`. Never point it at a real ledger. |
| Phase 1 exit path | One process fills BTC long at 50 000; a second process hydrates from PostgreSQL, sees the same position/cash (50 000), and closes it via `process_candle` at the 55 000 take-profit; a third process sees the closed trade (+5 000), cash 105 000, `positions.is_open=false`, one `trade_history` row, and two orders (entry has the client ID, exit has `NULL`). |
| Duplicate after restart | A fresh process reusing `client_order_id` raises `PaperOrderConflictError` before mutation; exactly one order and one open position remain. |
| Concurrent fills | Two processes fill BTC long and ETH short concurrently: both positions and orders persist, portfolio cash is 52 000 (no lost update). |
| Concurrent duplicate race | Two processes submit the same `client_order_id` concurrently: exactly one accepted, one conflict, one order/one position — the partial unique index plus the writer lock hold. |
| Busy writer | While one connection holds the advisory lock, a writer with a 0.2 s timeout raises `PaperLedgerBusyError` and writes nothing; after release the same request succeeds. |
| CI job | `.github/workflows/ci.yml::postgres-integration` starts `postgres:16-alpine`, loads `database/schema.sql`, installs with `uv --locked`, and runs the module with `--no-cov`. `ARES_REQUIRE_POSTGRES_INTEGRATION=1` makes a missing URL a hard failure, never a silent skip. Verified on GitHub Actions run 39742069953 (all 5 tests passed). |
| Verified locally (at the P1.4 commit) | Temporary PostgreSQL 16 container (schema from `database/schema.sql`): **5 passed in 5.2 s**; full suite **1108 passed / 80.10%** with the URL and **1103 passed + 1 skipped / 80.08%** without. Container removed. |

## P1.4b — real-PostgreSQL strategy route round-trip (verified 2026-10-22)

| Piece | Evidence |
|---|---|
| Opt-in module | `tests/test_postgres_strategy_integration.py` uses the same `ARES_TEST_POSTGRES_URL` / `ARES_REQUIRE_POSTGRES_INTEGRATION` guard and refuses a database name without `test`. |
| Isolation | The fixture deletes only `strategies`; it never truncates users or paper tables. The route app uses `httpx.ASGITransport` and overrides `get_db` with a real `async_sessionmaker`. |
| Round-trip | POST → GET → list returns the committed row; a separate engine observes JSONB `config`/`parameters`, `version=1`, `status=draft`, and `live_trading_enabled=false`. |
| Version and lifecycle | PUT bumps `version` to 2 and preserves draft/live/promotion fields; a row promoted directly to `backtesting` returns **409** and its name/version/status are unchanged; a `paused` row remains editable. |
| Rejection boundaries | POST/PUT lifecycle or live-enablement fields return **422** and do not write; missing rows return **404**. |
| Verification | Disposable `postgres:16-alpine` with `database/schema.sql`: **12 passed in 4.07 s**; combined with the ledger module **17 passed in 11.70 s**. Container removed. |
| CI follow-up | `.github/workflows/ci.yml::postgres-integration` ran both modules at that slice; the updated CI command had not yet been exercised by a GitHub Actions run. |

## P1.6 — role-based authorization (committed and pushed, verified 2026-10-21)

| Piece | Evidence |
|---|---|
| Canonical roles | `backend/core/roles.py`: `viewer`, `operator`, `admin`, `super_admin`. `user` is a legacy alias for `operator`; unknown values normalize to `viewer` (fail closed). |
| JWT role claim | `POST /auth/login` mints `{"sub": email, "role": normalized_role}`. `require_trading_access` and `require_live_control` verify the signature and role directly, with **no database lookup**, so `/live/kill` and `/live/arm` still work while PostgreSQL is down. A token minted before P1.6 has no role and is read-only until re-login. |
| API-key mapping | Possessing `API_SECRET_KEY` is the server-to-server operator boundary and maps to `admin`; it can execute paper trades and operate live controls. |
| Route gates | `/api/v1/execute` requires `operator`/`admin`/`super_admin`; `/live/mode`, `/live/start`, `/live/stop`, `/live/kill`, and `/live/arm` require the same. Read-only `/live/status`, `/live/positions`, `/live/orders`, `/live/audit`, and `/live/promotion` remain available to viewers. |
| Viewer denial | `tests/test_security/test_role_auth.py` sends a viewer JWT to all six protected routes on the real app and gets **403**; an operator JWT reaches body validation on `/execute` (**422**, not forbidden). The unit matrix covers viewer/operator/admin/super_admin, legacy `user`, unknown role, missing role, API key, and invalid token. |
| Migration | `migrations/versions/0004_role_hierarchy.py` finds the existing role check dynamically, rewrites `user` → `operator`, allows `viewer`/`operator`, and changes the default to `viewer`. `database/schema.sql` and `init.sql` match; `User.role` and `UserBase.role` default to `viewer`. |
| Real PostgreSQL 16 | Fresh `alembic upgrade head` produced the new constraint and `viewer` default. After `downgrade 0003`, a legacy `role='user'` row upgraded to `operator`; a later `role='user'` insert was rejected by `users_role_check`. The one-shot `--rm` container was stopped. |
| Mypy cleanup | The 22 pre-existing errors in 8 test/script files are fixed (annotations, unused ignores, exception-handler signature, `AgentState` import). `mypy .` is clean on **184 source files**; no safety gate or test assertion was weakened. |
| Counts | Full suite **1129 passed, 1 skipped / 80.29%**; `ruff check .` and `ruff format --check .` clean. |

## P1.5 — degraded health and Prometheus-backed metrics (committed and pushed, verified 2026-10-21)

| Piece | Evidence |
|---|---|
| Degraded health status | `/health` now returns **200** only when PostgreSQL, Redis, and ChromaDB all answer. Any unreachable dependency returns **503** with the same per-check JSON (`status: degraded`). Tests cover DB, Redis, ChromaDB, and all-down cases. |
| Compose consumes the signal | The backend healthchecks in `docker-compose.yml` and `docker/docker-compose.yml` already exit nonzero for any status other than 200, so the 503 makes the existing enriched check effective without command changes. |
| No metrics dependency on `_last_state` | `GET /api/v1/metrics` now calls `backend.core.metrics.get_metrics_snapshot()`; it returns HTTP requests, agent runs, agent errors, model fallbacks, live orders, and kill-switch state. `tests/test_monitoring/test_metrics_endpoint.py` patches `get_last_state` to raise and the endpoint still returns 200. |
| Real Prometheus registry | The snapshot sums the same labeled counters that the public `/metrics` mount serves; a test asserts `/metrics` contains `ares_agents_runs_total` and `ares_requests_total`. |
| Frontend contract | `MetricsResponse` and the analytics cards now use the new counter fields; `pnpm build` passes (TypeScript clean). |
| Counts | Full suite **1129 passed, 1 skipped / 80.29%**; `mypy .` clean on **184 source files**; `ruff check .` and `ruff format --check .` clean. |

The public `/metrics` mount remains the Prometheus scrape target. `/api/v1/metrics` is the
authenticated JSON convenience view over the same process-local counters.

## Phase 1 exit — Compose mid-trade restart (verified 2026-10-21)

| Piece | Evidence |
|---|---|
| Stack | `docker/docker-compose.yml` full stack: PostgreSQL 16, Redis, ChromaDB 1.5.9, backend, frontend, Prometheus, Grafana. `/health` returned 200 with `database/redis/chromadb = ok`; all services reported healthy after startup. |
| Startup fixes required | `.gitattributes` forces LF for shell scripts (the Windows checkout had CRLF, causing `exec /entrypoint.sh: no such file or directory`). The backend environment now forces container-internal `postgres`/`redis`/`chromadb` hosts instead of the host-oriented `.env` values. When `init.sql` has already created the schema, the entrypoint detects the missing Alembic version row and stamps `0001` before applying `0002`–`0004`. The Chroma image is pinned to **1.5.9** to match the Python client (0.5.0 only speaks v1); the 1.x image persists at **`/data`**, so the volume is mounted there instead of the 0.5.0 path. The 1.x image has no curl/python, so the Chroma container healthcheck is disabled and the backend starts on `service_started` while `/health` reports Chroma unavailability. |
| Concurrent fills | Two approved `/execute` calls ran concurrently through the HTTP API on distinct synthetic symbols. Both returned **200**, `ledger_persisted: true`, and distinct position IDs. Pre-restart portfolio: cash **96 493.0**, equity **99 996.5**, `open_positions=2`, `total_pnl=-3.5`; both positions present. |
| Full-stack restart | `docker compose restart` restarted all seven services. `/health` returned 200 again. The post-restart JSON matched the pre-restart snapshot **exactly** for `portfolio`, `positions`, `orders`, and `paper_record`; no fill was lost. |
| Idempotency after restart | Replaying `compose-exit-syn-btc` after the restart returned **409** (`client_order_id has already been used`) and the snapshot stayed identical. |
| Cleanup | Synthetic test rows were truncated, the paper account was reseeded, `ares-run-live` and `ares-daily-reporter` were restarted, and the temporary test key was removed. A unique local `API_SECRET_KEY` was then written to `.env` (never committed), so authenticated `/api/v1/*` now returns 200. |

The test deliberately used synthetic symbols so the background paper worker could not mark
or stop the positions during the restart window. The `/execute` approval checks, the
advisory-lock ledger, PostgreSQL persistence, and the Compose restart were the production
paths; the symbol name was the only test seam. The Chroma volume was migrated from the
0.5.0 path to `/data`; a container restart preserved `chroma.sqlite3` and `/health` stayed
200.

## Phase 2 — first slice: real market candles (verified 2026-10-22)

| Piece | Evidence |
|---|---|
| Candles endpoint | `GET /api/v1/market/candles?symbol=&interval=&limit=&source=` in `backend/routers/market.py`. It auto-selects Binance for the mapped crypto symbols and Yahoo for equities, validates interval/source/limit, caps the response at 500 candles, returns ascending deduplicated UTC epoch timestamps, and maps no-data/upstream failure/timeout to **404/502/504**. Mounted behind `verify_auth` in `backend/main.py`. |
| Response schema | `backend/schemas/market.py` defines `Candle`/`CandlesResponse` with finite floats and non-negative volume. |
| Dashboard | `frontend/src/app/markets/page.tsx` fetches real candles through `getCandles`; the chart is created once and disposed with `chart.remove()`; analysis is an explicit **Analyze** button action (no auto-run on mount or symbol change); a ref guards concurrent runs; the symbol select has a label; loading, error, and empty states are explicit, and run state is announced with `aria-live`. |
| Focused tests | `pytest tests/test_market_router.py -q` — **13 passed** (schema/limit/source validation, ordering, deduplication, 404, 502, 504, source selection). |
| Route auth | `pytest tests/test_security/test_route_auth.py -q` — **5 passed**; the new router is covered by the existing mount guard. |
| Real-source smoke check | Direct call on 2026-10-22 returned 5 AAPL candles from Yahoo and 5 BTC-USD candles from Binance. |
| Source timestamps | `yahoo.py` and `coingecko.py` now emit timezone-aware UTC timestamps instead of host-local naive times; `tests/test_data_sources.py` asserts the epoch. The smoke check showed the AAPL daily candle at **13:30 UTC** and BTC-USD at **00:00 UTC**. |
| Full verification (at that slice) | `pytest tests/ -q` — **1142 passed, 1 skipped / 80.54%**; `ruff check .` and `ruff format --check .` clean; `mypy .` clean on **187 files**. |
| Frontend build | `pnpm build` passed (Next 16.2.12, TypeScript clean). |

## Phase 2 — second slice: persisted dashboard settings (verified 2026-10-22)

| Piece | Evidence |
|---|---|
| Settings API | `backend/routers/settings.py` exposes `GET /api/v1/settings` and `PUT /api/v1/settings/preferences`, mounted behind `verify_auth` in `backend/main.py`. The GET response has a read-only `safety` block and a persisted `preferences` block; the PUT body is `DashboardPreferences` only. |
| Safety limits are read-only | `SafetyLimits` is built from the enforcing modules: `agents.risk.MAX_POSITION_SIZE_PCT` (**2.0%**), `agents.risk.MAX_RISK_SCORE` (**70.0**), `agents.consensus.REQUIRED_CONFIDENCE` (**80.0**), `live_max_drawdown_pct` (**15.0%**), promotion gate (**50 trades / 30 days**), and `live_trading_enabled` (default **false**). The preferences model uses `extra="forbid"`; sending `safety`, a cap, or a confidence field returns **422** and writes nothing. |
| Persisted preferences | `backend/schemas/settings.py` defines `DashboardPreferences` with `default_symbol` (1–20 chars, trimmed/uppercased, `^[A-Z0-9^.=:/-]+$`) and `live_refresh_seconds` (5–30 s). `backend/services/settings_service.py` loads defaults before the first save, merges new defaults over older JSON, and upserts `app_settings` with `ON CONFLICT (id) DO UPDATE ... RETURNING`. |
| Store and migration | At that slice, `database/schema.sql` and `database/init.sql` were byte-identical and defined **19 tables**, including the singleton `app_settings` row (`id SMALLINT PRIMARY KEY CHECK (id = 1)`, `preferences JSONB`, `updated_at`). `migrations/versions/0005_app_settings.py` adds the table/row/trigger idempotently; `alembic heads` reported **`0005_app_settings (head)`**. The schema now defines 21 tables; `0006_improvement_history` is the current head. |
| Frontend settings page | `frontend/src/app/settings/page.tsx` now loads from `GET /api/v1/settings` and saves through `PUT /api/v1/settings/preferences` (no `setTimeout`). It shows the enforced 2% cap, reads the API URL from `API_BASE_URL` (`NEXT_PUBLIC_API_URL`, default `localhost:8000`), renders no token/WebSocket preview, and has explicit loading/error/saved states with `htmlFor` labels, `aria-invalid`, and `aria-live`/`role="alert"`. |
| Preferences are consumed | `default_symbol` seeds dashboard quick analysis and the initial markets chart (a saved symbol outside the preset list is kept as a select option); `live_refresh_seconds` controls the `/live` polling interval. A missing settings store falls back to the built-in defaults on those pages. |
| Dead config removed | The unused `MAX_POSITION_SIZE_PCT` env field is gone from `configs/settings.py` and `.env.example`. `agents.risk.MAX_POSITION_SIZE_PCT` is the single 2% source; `tests/test_config.py` asserts the field is not environment-configurable. |
| Focused tests | `pytest tests/test_settings_router.py tests/test_settings_service.py -q` — **23 passed**; `pytest tests/test_schema.py -q` — **16 passed**; `pytest tests/test_security/test_route_auth.py -q` — **5 passed**, including `/api/v1/settings`. |
| Real PostgreSQL proof | Temporary PostgreSQL 16 container: fresh `alembic upgrade head` reached `0005_app_settings`; a second path at `0004` with `app_settings` dropped also upgraded cleanly and recreated the seeded row plus trigger; GET returned defaults; PUT ` eth-usd `/15 persisted as `ETH-USD`/15; a payload containing `safety.max_position_size_pct=100` returned **422**; a second Python process reloaded the persisted preferences. Container and temporary scripts were removed. |
| Full verification (at that slice) | `pytest tests/ -q` — **1196 passed, 1 skipped / 81.11%**; `mypy .` clean on **198 source files**; `ruff check .` and `ruff format --check .` clean; `pnpm build` passed. |

## Phase 2 — third slice: live polling, API errors, accessibility (verified 2026-10-22)

| Piece | Evidence |
|---|---|
| Live page polling | `frontend/src/app/live/page.tsx` fetches status and audit concurrently with `Promise.all`, keeps one refresh in flight, aborts the active request on unmount, pauses the interval while the document is hidden, resumes immediately on visibility, and force-refreshes after start/stop/kill/arm/mode actions so a stale in-flight poll cannot overwrite the action result. The interval still comes from `live_refresh_seconds`. |
| Pipeline polling | `frontend/src/lib/usePipelinePolling.ts` starts polling only after `POST /analyze` is accepted (avoiding the previous run's state), performs one status request at a time, polls immediately, aborts on unmount, backs off **1 → 2 → 4 → 8 s** on transient failures, and enforces the **60 s** safety timeout. `runAnalysis` rejects a second concurrent trigger. |
| API client | `frontend/src/lib/api.ts` gives every request a bounded timeout (30 s default; 10 s status/audit/agent, 20 s analyze/candles, 120 s backtest), honours caller `AbortSignal`s, exposes typed `ApiError` (with FastAPI `detail`) and `ApiTimeoutError`, and bounds `/auth/verify`. The existing 401 clear-and-redirect behavior is unchanged. |
| Accessibility | Root layout has a skip link to `#main-content`; `AuthGate` renders the focusable `main` target. The sidebar has `aria-label`s and `aria-current="page"`. Live actions have labelled status regions, error `role="alert"`, a labelled trading-mode select, and kill/arm dialogs with `role="dialog"`, `aria-modal`, labelled titles/descriptions, Escape handling, and safe initial focus. Strategy-builder inputs are labelled and toggle buttons expose `aria-pressed`. |
| Contrast | Muted small text was raised from `#52525b` to **`#8b8b93`** (5.86:1 on the base background) and `#71717a` to **`#a1a1aa`** (7.72:1); the `#3f3f46` captions were raised to `#8b8b93` as well. The `--color-text-muted` token now matches. |
| Verification (at that slice) | `pnpm build` passed (Next 16.2.12, TypeScript clean). `pytest tests/ -q` — **1196 passed, 1 skipped / 81.11%**; `ruff check .` and `ruff format --check .` clean; `mypy .` clean on **198 source files**. No safety gate or live-trading default changed; live remains paper-only and disabled by default. Frontend lint/typecheck/test CI and a manual axe/Lighthouse pass remain open. |

## Phase 2 — fourth slice: strategy draft persistence (verified 2026-10-22)

| Piece | Evidence |
|---|---|
| Draft API | `backend/routers/strategies.py` exposes authenticated `GET/POST /api/v1/strategies`, `GET/PUT /api/v1/strategies/{id}`. The router is mounted with `verify_auth` in `backend/main.py`; the route-auth test enumerates it. |
| Server-owned lifecycle | `backend/schemas/strategy.py` uses `extra="forbid"` for create/update. A request containing `status`, `live_trading_enabled`, `paper_trade_closed_trades`, or a promotion field returns **422** before the service runs. Create always lands as the table default `draft`; update only touches name/description/type/config/parameters and bumps `version`. |
| Editable boundary | `backend/services/strategy_service.py` permits edits only when the stored status is `draft` or `paused`; any other status returns **409**. The `UPDATE` re-checks that status, so a concurrent promotion fails closed. A missing row is **404**; a store failure is **503**. The trading, Risk, consensus, promotion, and live paths do not read drafts from this service. |
| Persistence shape | The existing `strategies` table stores `config JSONB` (`indicators`) and `parameters JSONB` (`position_size_pct`, `stop_loss_pct`, `take_profit_pct`). No schema or migration change was needed; `0005_app_settings` remained the Alembic head at that slice. |
| Frontend builder | `frontend/src/app/strategy-builder/page.tsx` now lists saved drafts, loads one into the form, creates or updates it, and shows explicit loading/error/saved states. Draft parameters are controlled inputs; `aria-pressed` and labels remain. The page states that saving never enables live trading. |
| Backtest handoff | Supported draft types link to `/backtests?strategy=...`; the backtests page accepts only its real `momentum`, `mean_reversion`, `trend_following`, or `breakout` options. Unsupported draft types show a disabled explanation instead of sending an invalid request. |
| Focused tests | `pytest tests/test_strategy_router.py tests/test_strategy_service.py -q` — **29 passed**: create/list/get/update, normalization, version bump, JSON row parsing, 404/409/422/503, rejection of lifecycle/live fields, and fail-closed promotion-race handling. The route-auth test now enumerates `/api/v1/strategies`. |
| Full verification (at that slice) | `pytest tests/ -q` — **1196 passed, 1 skipped / 81.11%**; `ruff check .` and `ruff format --check .` clean; `mypy .` clean on **198 source files**; `pnpm build` passed. No safety gate, live default, promotion rule, or test assertion changed. |
| PostgreSQL follow-up (closed 2026-10-22) | The unit tests still use a mock SQLAlchemy session; the real-PostgreSQL round-trip now lives in `tests/test_postgres_strategy_integration.py` and covers create/list/get/update, JSONB, version bumps, 422/409/404. |

## Phase 2 — fifth slice: frontend lint, typecheck, and tests (verified 2026-10-22)

| Piece | Evidence |
|---|---|
| ESLint | `frontend/eslint.config.mjs` is an ESLint 9 flat config built on `eslint-config-next/core-web-vitals` (16.4.2). `pnpm lint` runs `eslint . --max-warnings=0` and finishes with no warnings. `react-hooks/set-state-in-effect` is explicitly disabled for the existing fetch-on-mount pages; the other React Compiler rules remain enabled. |
| Type check | `pnpm typecheck` runs `tsc --noEmit`; clean. |
| Tests | Vitest 5.0.5 with jsdom and Testing Library. `pnpm test` — **14 passed** across 3 files: API detail/timeout/abort/API-key handling, pipeline polling (starts only after POST acceptance, backs off, single-flight, 60 s timeout), and `AuthGate` (redirect without a key, main landmark with one). |
| Fixes found by lint | `PriceTicker` no longer references `connect` before its declaration and cancels reconnects on cleanup; `EquityCurveChart` computes drawdown through a module-level loop instead of mutating a render-scope variable; the 401 redirect uses `location.replace`. No trading or safety behavior changed. |
| CI | The `frontend` job in `.github/workflows/ci.yml` now runs `pnpm lint`, `pnpm typecheck`, `pnpm test`, then `pnpm build`. |
| Verification | `pnpm lint`, `pnpm typecheck`, `pnpm test` (**14 passed**), and `pnpm build` (Next 16.2.12) all pass locally. No backend or safety-path change in this slice. |

## Phase 2 — sixth slice: read-only multi-turn chat (verified 2026-10-22)

| Piece | Evidence |
|---|---|
| Chat API | `backend/routers/chat.py` exposes authenticated `POST /api/v1/chat`, mounted behind `verify_auth` in `backend/main.py`. The body is `{messages:[{role:"user"|"assistant",content}]}` with **1–20** turns and **1–4000** characters per turn; the last turn must be from the user. The response is `{reply, model, fallback_used}`. |
| Stateless history | There is no conversation table and no server-side memory. The frontend sends the recent turns with each request and the backend prepends a fixed system prompt. The single-user API-key deployment gets real multi-turn context without inventing a per-user store. |
| Read-only safety | The service has no tools and no execution path. The system prompt forbids placing/modifying/cancelling orders, changing modes or the kill switch, promoting strategies, fabricating prices/positions/PnL, requesting secrets, and bypassing Risk, consensus, position, drawdown, or promotion gates. A chat reply cannot create a trade. |
| Model chain | `configs/models.yaml` gains a `chat` entry with free-tier IDs only; `AgentModelConfig` appends the configured universal fallback. An exhausted chain, an error envelope (including the NoOp client), or empty/whitespace content returns **503**, never a fabricated reply. |
| Service | `backend/services/chat_service.py` caches one service and reuses the standard `ModelRouter`/circuit-breaker/queue/retry stack. It logs the fallback model and exposes `reset_chat_service()` for tests. |
| Frontend chat | `frontend/src/app/chat/page.tsx` keeps the conversation in React state, sends the last 20 turns per request, shows model/fallback metadata, keeps a failed user turn visible, offers retry, and uses an empty state that states the read-only boundary. The log has `role="log"`/`aria-live`, errors have `role="alert"`, the input has a real label and `aria-describedby`, the log exposes `aria-busy`, and Enter sends. |
| Tests | `pytest tests/test_chat_router.py tests/test_chat_service.py -q` — **17 passed**; `tests/test_security/test_route_auth.py` adds the unauthenticated **401**. `pnpm test` — **18 passed** in 4 files, including a chat-page test that proves the second request contains the prior user and assistant turns. |
| Verification (at that slice) | `pytest tests/ -q` — **1214 passed, 1 skipped / 81.31%**; `ruff check .` and `ruff format --check .` clean; `mypy .` clean on **203 source files**; `pnpm lint`, `pnpm typecheck`, `pnpm test` (**18 passed**), and `pnpm build` pass. No safety gate, live default, promotion rule, or test assertion changed. |
| Not yet run | No live OpenRouter request was made from this slice; model availability is still checked by the existing roster probe rather than by a real request in tests. Catalog drift remains gap #9. |

## Phase 2 — seventh slice: opt-in local chat fallback (verified 2026-10-24)

| Piece | Evidence |
|---|---|
| Provider | `agents/client.py` routes `local/` IDs to `LOCAL_LLM_BASE_URL`, strips the prefix before the request, sends no `Authorization` header, injects `reasoning_effort="off"`, and uses the provider's local timeout. |
| Gate | `agents/local_gate.py` is a process-wide semaphore shared by every `ModelRouter`; default `max_concurrent=1`, queue timeout 20 s. A busy local model raises `LocalModelBusyError`, which skips that candidate without retrying or recording a breaker failure. |
| Roster and chain | `configs/models.yaml` has a separate `local_chat` entry (`local/qwen3.6-35b-a3b-ud-q4_k_m`). When local is enabled and a remote provider exists, the chat chain is the remote free chain → local; with no remote provider it is local-only. The remote free-tier `chat` chain is unchanged. A missing `local_chat` entry, busy gate, exhausted chain, or empty text returns **503**. |
| Settings | `LOCAL_LLM_ENABLED=false`, base URL default `http://127.0.0.1:8080/v1`, timeout 90 s, max concurrent 1, queue timeout 20 s. Because the dev Compose stack publishes the backend on host 8080, `.env.example` uses `http://host.docker.internal:8081/v1` for Compose and documents `127.0.0.1:8080` for a host-run backend. No model is bundled and no download is started. |
| Safety scope | Chat remains read-only: no tools, sub-agents, live web/news retrieval, or trading actions. Local scope is chat-only; pipeline agents remain on the remote chain. The gate is per process, not a distributed lock. |
| Tests | `pytest tests/test_local_gate.py tests/test_client.py tests/test_router.py -q` — **27 passed**; the chat suite is **21 passed**; full suite **1229 passed, 2 skipped / 81.90%**; `ruff` and `mypy` clean on **206 files**. |
| Frontend | `frontend/src/lib/api.ts` chat timeout is 120 s so a slow local fallback is not cut off before the backend's 90 s model timeout; `pnpm lint`, `pnpm typecheck`, `pnpm test` (**18 passed**), and `pnpm build` pass. |
| Live smoke (2026-10-24) | Strata on `127.0.0.1:8080` exposed `qwen3.6-35b-a3b-ud-q4_k_m`. With remote keys blanked in the smoke process, a direct `LLMClient` call returned `LOCAL OK` in **0.49 s**, `ChatService` used the local-only chain and returned `LOCAL CHAT OK` in **0.99 s**, and `POST /api/v1/chat` returned **200** with `LOCAL ROUTE OK`, `model=local/qwen3.6-35b-a3b-ud-q4_k_m`, and `fallback_used=false`. No remote request was made and no API key was sent. |
| Not in CI | The live smoke is manual because CI has no model server; pipeline-local routing remains disabled. |

## Phase 2 — eighth slice: accessibility audit (verified 2026-10-24)

| Piece | Evidence |
|---|---|
| Method | Production build (`pnpm build`) served at `127.0.0.1:3000`. Lighthouse 13.5.0 ran its accessibility category on `/login`; axe-core 4.14.0 ran through Chrome DevTools Protocol on all 16 authenticated routes. The audit set a dummy tab-scoped `ares_api_key` and stubbed `/api/v1/*` with **503**, so no real key was read or sent and no 401 redirect cleared the session. |
| Result | Lighthouse `/login`: **100** with no failing audits. axe-core: **0 violations across 16 routes** (`/`, `/markets`, `/portfolio`, `/risk`, `/live`, `/paper-trading`, `/strategy-builder`, `/backtests`, `/signals`, `/journal`, `/agents`, `/memory`, `/logs`, `/analytics`, `/chat`, `/settings`). |
| Fixes | Login submit contrast raised from **4.46:1** to about **6.3:1** (`#6366f1` → `#4f46e5`, hover `#4338ca`); active-nav text raised to `#818cf8`; the market chart uses `role="figure"` instead of `role="img"` so its focusable attribution link is valid; `/live` loading and error states include an `h1`; `/backtests` strategy, interval, days, and capital controls have associated labels; the chat log is focusable and named. |
| Scope | The audit covers `/login` plus every route's rendered shell and loading/error states. Data-populated tables, charts, and dialogs were not exercised because the API was stubbed to 503; a pass with real data remains optional follow-up. |
| Verification | `pnpm lint`, `pnpm typecheck`, `pnpm test` (**18 passed**), and `pnpm build` pass after the fixes. No safety gate, API behavior, or test assertion changed. |

## Phase 3 — first slice: improvement metric correctness (verified 2026-10-24)

| Piece | Evidence |
|---|---|
| Metric | `win_rate` is now `execution_rate` in `agents/improvement.py` and the metrics endpoint; the value always measured executed/total, not winning trades. `WIN_RATE_DECLINE_THRESHOLD` became `EXECUTION_RATE_DECLINE_THRESHOLD`, and the check and description now say execution rate. |
| Safety | The execution-rate decline record no longer suggests `min_consensus_confidence: 75.0`; it keeps only `max_drawdown_pct: 15.0`. This removes a generated suggestion that contradicted the >80% consensus gate. |
| API | `GET /api/v1/agents/improvements` now includes each record's `suggested_params` so an operator can review a suggestion before applying it; the apply endpoint still only marks `applied`. |
| Tests | `pytest tests/test_improvement.py -q` — **16 passed**, including an assertion that the decline record has no `min_consensus_confidence` key. Full suite **1229 passed, 2 skipped / 81.90%**; `ruff` and `mypy` clean on **206 files**. |
| Open | History was still process-local and `analyze()` was not called by the pipeline at that slice; both were closed by the next slice. |

## Phase 3 — second slice: durable improvement history and pipeline wiring (verified 2026-10-24)

| Piece | Evidence |
|---|---|
| Engine | `agents/improvement.py::analyze(reflection_output, history=...)` analyzes an explicit oldest-first window and never mutates process globals in that mode; `metrics_for(history)` exposes the same aggregate. Record IDs are UUIDs so they match the PostgreSQL primary key and cannot collide within a millisecond. |
| Schema | `database/schema.sql` and `database/init.sql` are byte-identical and define **21 tables**. `reflection_runs` stores structured reflection output (evaluation, confidence accuracy, suggestions, knowledge updates, errors); `improvement_records` stores advisory suggestions with metrics, rationale, suggested params, and applied state. Indexes cover recency, category, unapplied rows, and a unique `(reflection_run_id, category, description)` retry guard. |
| Migration | `migrations/versions/0006_improvement_history.py` creates both tables/indexes idempotently and drops them on downgrade. Disposable PostgreSQL 16: fresh `alembic upgrade head` reached **`0006_improvement_history`**; `downgrade 0005_app_settings` removed both tables; re-upgrade restored them. No real database was touched; container removed. |
| Service | `backend/services/improvement_service.py` inserts the reflection run, loads the last 100 committed runs **excluding the current row**, runs the engine, inserts generated records, and commits in one transaction. Failures roll back. `record_reflection_improvement` is a **best-effort** hook with a 5 s timeout that logs and swallows every failure. |
| API | `GET /api/v1/agents/improvements` (limit 1–100), `POST /api/v1/agents/improvements/apply`, and `GET /api/v1/agents/improvements/metrics` now read/write PostgreSQL. Store failures return **503**; unknown or malformed record IDs return **404**; applying twice is idempotent and only marks the record applied. |
| Wiring | `Supervisor` accepts an optional `post_run_hook`, invoked after `log_execution` in both `run` and `stream_analysis`. `backend/routers/analysis.py` and `scripts/run_live.py` pass the persistence hook; backtests intentionally do not record improvement history. A hook failure is logged and never changes the pipeline result. |
| Safety | Suggestions remain advisory: apply marks a record, never mutates `configs/`, a threshold, a position cap, a promotion gate, or the kill switch. The execution-rate decline record still proposes only `max_drawdown_pct: 15.0`. No safety gate or test assertion changed. |
| Tests | Engine **20 passed**, service **11 passed**, agents router **7 passed**, supervisor **30 passed**; the real-PostgreSQL module adds **6 passed**. Combined PostgreSQL run: **23 passed** (5 ledger + 12 strategy + 6 improvement). Full suite **1253 passed, 3 skipped / 82.17%**; `ruff check .` and `ruff format --check .` clean; `mypy .` clean on **211 source files**. |
| CI | `.github/workflows/ci.yml::postgres-integration` runs all three PostgreSQL modules. GitHub Actions run **40097868595** passed it (46 s, 23 tests) along with `lint`, `test`, `frontend`, and `docker`; gap #15 is closed. |

## Phase 3 — third slice: Prometheus alert rules and one monitoring set (verified 2026-10-24)

| Piece | Evidence |
|---|---|
| Alert rules | `docker/monitoring/alert-rules.yml` defines **7 rules** in three groups: availability (`AresBackendDown`, `AresBackendHighErrorRate`, `AresBackendSlowRequests`), agents (`AresAgentErrorRateHigh`, `AresModelFallbackSpike`), and live trading (`AresLiveOrderFailures`, `AresKillSwitchActive`). Every expression references a metric emitted by `backend/core/metrics.py`. |
| Delivery gap | The dev stack has no Alertmanager target. Rules evaluate and appear on Prometheus `/alerts` and in the `ALERTS` series, but nothing pages. That is an operational follow-up, not a safety gate. |
| Single config set | Both `docker-compose.yml` and `docker/docker-compose.yml` mount `docker/monitoring/prometheus.yml`, `alert-rules.yml`, and the Grafana provisioning files. The stale gitignored `docker/prometheus/` and `docker/grafana/` copies were removed and their ignore rules dropped; the richer 10-panel overview dashboard was preserved as `docker/monitoring/grafana-overview.json` and is mounted alongside the trading dashboard. |
| Validation | `promtool check config` reports 1 rule file and valid syntax; `promtool check rules` reports **7 rules**. `docker compose ... config --quiet` passes for both compose files. `pytest tests/test_infra_config.py -q` — **18 passed**, including rule fields, emitted-metric coverage, compose mounts, and dashboard JSON. Full suite **1259 passed, 3 skipped / 82.17%**; `ruff` and `mypy` clean on **211 files**. |
| CI | GitHub Actions run **40099879748** passed all five jobs: `lint`, `test`, `postgres-integration` (23 tests), `frontend`, and `docker`. |
| Safety | Alerting is read-only observability. No rule, dashboard, or compose change touches the kill switch, approval mode, promotion gate, or a trading threshold. |

## Post-merge dependency alignment (verified 2026-10-25)

| Piece | Evidence |
|---|---|
| Failure | The master sync bumped `react` to 19.3.1 but left `react-dom` at `^19.1.0`, which resolved 19.2.7. CI run **40211715708** failed the `frontend` job with `Incompatible React versions`. |
| Fix | `frontend/package.json` now requires `react-dom ^19.3.1`; `frontend/pnpm-lock.yaml` resolves both packages to **19.3.1**. |
| Verification | `pnpm lint`, `pnpm typecheck`, `pnpm test` (**18 passed**), and `pnpm build` pass locally. GitHub Actions run **40212632255** passed all five jobs. |
| Safety | Dependency-only change; no trading, safety, auth, or API behavior changed. |

## Red / known gaps

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 1 | ~~Concurrent paper-ledger writes are last-writer-wins~~ | Closed by P1-C: writers serialize on `pg_try_advisory_xact_lock` across API/worker/runner, with an in-process cache lock. Busy writers fail closed with 503. | ~~P1~~ fixed |
| 2 | `/execute` trusts the authenticated caller's agent payload | The server recomputes consensus and caps size, but an API-key holder can supply synthetic Market Analyst/Quant/Risk outputs. There is no signed or expiring signal token. The API key remains the trust boundary. | P2 |
| 3 | ~~No role-based authorization on trading/live routes~~ | Closed by P1.6: viewer JWTs get 403 on `/execute` and all live controls; operator+ required; JWT role claim and API-key mapping tested on the real routes. | ~~P1~~ fixed |
| 4 | ~~`mypy` fails~~ | Closed: the 22 errors in 8 test/script files are fixed, `mypy .` is clean on 184 files, and CI run 39742069953 passed `lint`. | ~~P1~~ fixed |
| 5 | `/analyze` concurrency/cost control absent | global `_last_state`, unbounded `BackgroundTasks`; auth is required, but runs are still not isolated. `/api/v1/metrics` no longer reads `_last_state`; `/agents/status` and `/risk` still do. | P1 |
| 6 | Kill-switch latch is process-local | a Redis outage latches each process; `/live/arm` clears the API process, but a runner that also latched stays blocked until restarted (fail-closed, never auto-trades) | P1 operational |
| 7 | ~~No automated PostgreSQL integration test in CI~~ | Closed by P1.4/P1.4b: `postgres-integration` runs hydrate → fill → restart → close, duplicate IDs, concurrent fills, and the busy lock, plus the strategy route → service → JSONB round-trip on `postgres:16-alpine`; the local default suite skips all three modules without `ARES_TEST_POSTGRES_URL`. | ~~P2~~ fixed |
| 8 | ~~Remaining UI polling and accessibility gaps~~ | Closed 2026-10-22: `/live` fetches status/audit concurrently, pauses when hidden, guards in-flight refreshes, aborts on unmount, and force-refreshes after controls; `usePipelinePolling` single-polls with abort/backoff; `api.ts` has bounded timeouts and typed errors; skip link, navigation/dialog ARIA, labelled controls, and stronger muted-text contrast are in place. The 2026-10-24 audit (Lighthouse 13.5.0, axe-core 4.14.0) found and closed five more issues across the route shells. | ~~P2~~ fixed |
| 9 | Model catalog removals are not checked in CI | manual check only; `scripts/test_free_models.py` exists but is not a CI job | P2 |
| 10 | Existing deployments need a migration | `alembic upgrade head` is required for `0003_order_idempotency`, `0004_role_hierarchy`, `0005_app_settings`, and `0006_improvement_history` (plus P1-A columns). `0004` rewrites legacy `user` → `operator` and makes `viewer` the default; `0005` creates the singleton `app_settings` row and its trigger, so `/api/v1/settings` returns **503** until it is applied; `0006` creates `reflection_runs`/`improvement_records`, so improvement list/metrics return **503** until it is applied. `init.sql` only runs on first container start; the backend entrypoint stamps `0001` when `init.sql` initialized the schema, then applies the later idempotent revisions. Old short **positions** still cannot be inferred and default to long. | Operational |
| 11 | ~~Local `.env` API key is the default placeholder~~ | Closed locally: a unique `API_SECRET_KEY` is set in `.env` (never committed), and authenticated `/api/v1/*` returns 200. Other environments must set their own key. | ~~Operational~~ fixed locally |
| 12 | ~~Frontend lint/typecheck/test is not a CI job~~ | Closed 2026-10-22: ESLint 9 flat config (`pnpm lint`, zero warnings), `pnpm typecheck` (`tsc --noEmit`), and Vitest/Testing Library (**18 tests**) run in the `frontend` CI job before `pnpm build`. | ~~P2~~ fixed |
| 13 | ~~Chat is a pipeline trigger, not a conversational agent~~ | Closed 2026-10-22: `POST /api/v1/chat` sends the bounded history through a free-tier fallback chain and returns a model reply with fallback metadata. The page keeps multi-turn state and the new test proves prior turns are sent. Chat remains read-only: it has no tools and cannot place orders, change modes, promote strategies, or bypass safety gates. | ~~P2~~ fixed |
| 14 | Local chat is chat-only and process-gated | Live smoke passed 2026-10-24 against Strata `qwen3.6-35b-a3b-ud-q4_k_m` (direct 0.49 s, ChatService 0.99 s, local-only). Pipeline agents still use remote models; a local pipeline needs schema-compliance and latency evidence before it can be proposed. The gate is process-local, so multiple backend processes are not serialized against each other. | P2 |
| 15 | ~~Updated PostgreSQL CI command has not run on GitHub Actions~~ | Closed 2026-10-24: GitHub Actions run **40097868595** ran `.github/workflows/ci.yml::postgres-integration` with all three modules (5 ledger + 12 strategy + 6 improvement = **23 passed**, no skip) on `postgres:16-alpine`. | ~~P2~~ fixed |
| 16 | Accessibility audit did not exercise data-populated states | The 2026-10-24 pass used a 503 API stub, so tables, charts, and dialogs with real data were not audited. The route shells, login, and loading/error states are clean. | P3 |
| 17 | ~~Improvement history is in-memory and the engine is not wired into the pipeline~~ | Closed 2026-10-24: `reflection_runs`/`improvement_records` (migration `0006`) persist structured reflection and suggestions; the supervisor post-run hook calls the engine after every production pipeline run, best-effort; the API reads PostgreSQL and returns 503 on store failure. `analyze(history=...)` keeps trend context across restarts. | ~~P2~~ fixed |

Full plan and acceptance criteria: `docs/05-NEXT.md`. Decisions: `docs/04-DECISIONS.md`.

## Doc accuracy

README documents the required `API_SECRET_KEY` and dashboard login instead of quoting
stale test counts. The milestone table is historical; per-area truth lives here.
The conventional docs set added on 2026-10-22 (`docs/PRD.md`, `docs/API.md`,
`docs/DATABASE.md`, `docs/SETUP.md`, `docs/DEPLOYMENT.md`,
`docs/AUTH_SECURITY.md`, `docs/MCP.md`, `docs/INTEGRATIONS.md`,
`docs/TESTING.md`, `docs/DEBUGGING.md`, `docs/TASKS.md`, `docs/ROADMAP.md`,
`docs/DECISIONS.md`, `docs/CONVENTIONS.md`, `docs/FEATURES.md`,
`docs/IMPLEMENTATION.md`) summarizes and links to the numbered ICM docs rather
than replacing them.
