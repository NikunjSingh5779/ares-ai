<!-- docs/02-STATUS.md -->
# Status — verified state

**Last verified:** 2026-10-21
**Branch:** `fix/orchestration-reliability-frontend` — 5 commits ahead / 4 behind `master`.
P1-A is committed as `9c16122`; P1-B (approved-only `/execute` plus client-order
idempotency) is committed as `feat(paper): require approved execution and client order
ids`. The working tree is clean and the branch is not pushed.
**Method:** commands run locally against the working tree, not labels copied from earlier docs.

## Green

| Check | Command | Result |
|---|---|---|
| Test suite | `pytest tests/ -q` | **1088 passed**, 2 warnings |
| Coverage | `pytest tests/ -q` | **79.92%** (gate 78%) |
| Structure | `pytest tests/test_icm_structure.py -q` | **20 passed** — contracts exist, entry file small, links resolve |
| Lint | `ruff check .` | clean |
| Format | `ruff format --check .` | clean |
| Paper-ledger tests | `pytest tests/test_paper_trading_ledger.py -q` | **21 passed** — hydration, atomic write, duplicate ID, rejection/rollback, restart mid-trade |
| Trading-route tests | `pytest tests/test_trading_router.py -q` | **16 passed** — approval, derivation, 409/422/503, non-finite rejection |
| Schema tests | `pytest tests/test_schema.py -q` | **15 passed** — ledger/idempotency columns, init/schema parity, migration splitter |
| Targeted mypy | six P1-B production modules | clean |
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
It does **not** make concurrent writers safe: API, worker, and runner still use
last-writer-wins and have no row lock or optimistic version.

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

P1-B closes the raw-body `/execute` gap and the duplicate-order half of P1.3. It does
**not** add row locking or optimistic versions, so simultaneous API/worker/runner writes
can still lose an update.

## Red / known gaps

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 1 | Concurrent paper-ledger writes are last-writer-wins | API, worker, and runner each refresh then persist; `client_order_id` prevents duplicate requests, but there is no row lock or optimistic version. A simultaneous fill/mark can overwrite the other process. | P1 |
| 2 | `/execute` trusts the authenticated caller's agent payload | The server recomputes consensus and caps size, but an API-key holder can supply synthetic Market Analyst/Quant/Risk outputs. There is no signed or expiring signal token. The API key remains the trust boundary. | P2 |
| 3 | No role-based authorization on trading/live routes | any valid API key or JWT reaches live controls; single-user bootstrap limits exposure, but a seeded non-admin JWT is operator-level. | P1 |
| 4 | `mypy` fails | **22 errors in 8 files**, all in `tests/` + `scripts/` (6 in `test_test_free_models.py`, 4 in `test_error_handlers.py`, 3 in `test_analysis_router.py`, 3 in `test_paper_trading_worker.py`, 2 in `test_supervisor.py`, 2 in `scripts/test_free_models.py`, 1 each in `test_safety_edge_cases.py` and `test_engine_edge_cases.py`) | P1 (CI red) |
| 5 | `/analyze` concurrency/cost control absent | global `_last_state`, unbounded `BackgroundTasks`; auth is required, but runs are still not isolated | P1 |
| 6 | Kill-switch latch is process-local | a Redis outage latches each process; `/live/arm` clears the API process, but a runner that also latched stays blocked until restarted (fail-closed, never auto-trades) | P1 operational |
| 7 | No automated PostgreSQL integration test in CI | the real-DB proofs are manual; mocked sessions still cannot validate every SQL column or the unique-index race | P2 |
| 8 | UI has mock data and fake settings | `frontend/src/app/markets/page.tsx:81`, `settings/page.tsx` (no API call, 10% vs backend 2%) | P2 |
| 9 | Model catalog removals are not checked in CI | manual check only; `scripts/test_free_models.py` exists but is not a CI job | P2 |
| 10 | Existing deployments need a migration | `alembic upgrade head` is required for `0003_order_idempotency` (and P1-A columns); `init.sql` only runs on first container start. Old short **positions** still cannot be inferred and default to long. | Operational |

Full plan and acceptance criteria: `docs/05-NEXT.md`. Decisions: `docs/04-DECISIONS.md`.

## Doc accuracy

README documents the required `API_SECRET_KEY` and dashboard login instead of quoting
stale test counts. The milestone table is historical; per-area truth lives here.
