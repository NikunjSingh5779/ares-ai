<!-- docs/02-STATUS.md -->
# Status — verified state

**Last verified:** 2026-10-21
**Branch:** `fix/orchestration-reliability-frontend` — 7 commits ahead / 4 behind `master`.
P1-A is committed as `9c16122`; P1-B (approved-only `/execute` plus client-order
idempotency) is committed as `feat(paper): require approved execution and client order
ids`; P1-C (paper writer lock) is committed as `fix(paper): serialize ledger writers with
an advisory lock`; P1.4 (real-PostgreSQL integration job) is committed as
`test(paper): run the ledger suite against real PostgreSQL in CI`.
`origin/fix/orchestration-reliability-frontend` contains P1.4 (`b6b5bea`). GitHub Actions run
39601089127 passed `test`, `postgres-integration`, `frontend`, and `docker`; only `lint`
failed, on the 22 pre-existing mypy errors (gap 4).
**Method:** commands run locally against the working tree, not labels copied from earlier docs.

## Green

| Check | Command | Result |
|---|---|---|
| Test suite | `pytest tests/ -q` | **1103 passed, 1 skipped**, 2 warnings (integration module skips without `ARES_TEST_POSTGRES_URL`) |
| Coverage | `pytest tests/ -q` | **80.08%** default; **80.10%** with the integration job (gate 78%) |
| Structure | `pytest tests/test_icm_structure.py -q` | **20 passed** — contracts exist, entry file small, links resolve |
| Lint | `ruff check .` | clean |
| Format | `ruff format --check .` | clean |
| PostgreSQL integration | `ARES_TEST_POSTGRES_URL=... pytest tests/test_postgres_integration.py -q` | **5 passed** — real hydrate → fill → restart → close, duplicate ID, concurrent fills, one-winner duplicate race, busy lock → retry |
| CI PostgreSQL job | GitHub Actions `CI` run 39601089127 | **passed** on `postgres:16-alpine` in 46 s — all 5 tests, no skip |
| Paper-ledger tests | `pytest tests/test_paper_trading_ledger.py -q` | **34 passed** — hydration, atomic write, duplicate ID, writer lock, rejection/rollback, restart mid-trade |
| Trading-route tests | `pytest tests/test_trading_router.py -q` | **17 passed** — approval, derivation, 409/422/503, busy-lock retry |
| Schema tests | `pytest tests/test_schema.py -q` | **15 passed** — ledger/idempotency columns, init/schema parity, migration splitter |
| Worker tests | `pytest tests/test_paper_trading_worker.py -q` | **13 passed** — ledger delegation, locked symbol hydration |
| Targeted mypy | P1-B/P1-C production modules | clean |
| PostgreSQL 16 P1-C check | temporary container: concurrent fills, duplicate client ID, held lock → 503-equivalent busy error, released lock retry, cancelled writer | passed; no leaked advisory locks; container and script removed |
| PostgreSQL 16 P1-B check | temporary container: fresh `upgrade head`, P1-A schema → `stamp 0002` → `upgrade head`, duplicate execute before/after restart | passed; container and temporary scripts removed |
| Frontend build | `pnpm build` (in `frontend/`) | passed (P1-B client wrapper update) |
| API ↔ frontend paths | `app.openapi()` vs `src/lib/api.ts` | every path resolves |

## P0 fixes landed (2026-10-21)

| Fix | Evidence |
|---|---|
| Auth on every non-public route | `backend/main.py` mounts every domain router with `Depends(verify_auth)`; `tests/test_security/test_route_auth.py` enumerates `/api/v1` routes and fails if one is unprotected. Default/empty `API_SECRET_KEY` returns 503; no `API_DEBUG` bypass. |
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
because each process has its own cache. Role authorization (P1.6) and a signed signal
token (P2) remain open.

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
| CI job | `.github/workflows/ci.yml::postgres-integration` starts `postgres:16-alpine`, loads `database/schema.sql`, installs with `uv --locked`, and runs the module with `--no-cov`. `ARES_REQUIRE_POSTGRES_INTEGRATION=1` makes a missing URL a hard failure, never a silent skip. Verified on GitHub Actions run 39601089127 (46 s, all 5 tests passed). |
| Verified locally | Temporary PostgreSQL 16 container (schema from `database/schema.sql`): **5 passed in 5.2 s**; full suite **1108 passed / 80.10%** with the URL and **1103 passed + 1 skipped / 80.08%** without. Container removed. |

## Red / known gaps

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 1 | ~~Concurrent paper-ledger writes are last-writer-wins~~ | Closed by P1-C: writers serialize on `pg_try_advisory_xact_lock` across API/worker/runner, with an in-process cache lock. Busy writers fail closed with 503. | ~~P1~~ fixed |
| 2 | `/execute` trusts the authenticated caller's agent payload | The server recomputes consensus and caps size, but an API-key holder can supply synthetic Market Analyst/Quant/Risk outputs. There is no signed or expiring signal token. The API key remains the trust boundary. | P2 |
| 3 | No role-based authorization on trading/live routes | any valid API key or JWT reaches live controls; single-user bootstrap limits exposure, but a seeded non-admin JWT is operator-level. | P1 |
| 4 | `mypy` fails | **22 errors in 8 files**, all in `tests/` + `scripts/` (6 in `test_test_free_models.py`, 4 in `test_error_handlers.py`, 3 in `test_analysis_router.py`, 3 in `test_paper_trading_worker.py`, 2 in `test_supervisor.py`, 2 in `scripts/test_free_models.py`, 1 each in `test_safety_edge_cases.py` and `test_engine_edge_cases.py`) | P1 (CI red) |
| 5 | `/analyze` concurrency/cost control absent | global `_last_state`, unbounded `BackgroundTasks`; auth is required, but runs are still not isolated | P1 |
| 6 | Kill-switch latch is process-local | a Redis outage latches each process; `/live/arm` clears the API process, but a runner that also latched stays blocked until restarted (fail-closed, never auto-trades) | P1 operational |
| 7 | ~~No automated PostgreSQL integration test in CI~~ | Closed by P1.4: `postgres-integration` runs hydrate → fill → restart → close, duplicate IDs, concurrent fills, and the busy lock on `postgres:16-alpine`; the local default suite skips the module without `ARES_TEST_POSTGRES_URL`. | ~~P2~~ fixed |
| 8 | UI has mock data and fake settings | `frontend/src/app/markets/page.tsx:81`, `settings/page.tsx` (no API call, 10% vs backend 2%) | P2 |
| 9 | Model catalog removals are not checked in CI | manual check only; `scripts/test_free_models.py` exists but is not a CI job | P2 |
| 10 | Existing deployments need a migration | `alembic upgrade head` is required for `0003_order_idempotency` (and P1-A columns); `init.sql` only runs on first container start. Old short **positions** still cannot be inferred and default to long. | Operational |

Full plan and acceptance criteria: `docs/05-NEXT.md`. Decisions: `docs/04-DECISIONS.md`.

## Doc accuracy

README documents the required `API_SECRET_KEY` and dashboard login instead of quoting
stale test counts. The milestone table is historical; per-area truth lives here.
