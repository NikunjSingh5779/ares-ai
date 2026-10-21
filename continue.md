# CONTINUE.md — ARES AI handoff

**Last updated:** 2026-10-21
**Repository:** `C:\Users\ASUS\ares-ai`
**Branch:** `fix/orchestration-reliability-frontend`
**Head commit:** `test(paper): run the ledger suite against real PostgreSQL in CI` (read
the hash with `git log -1 --format=%h`).
**Branch position:** **7 commits ahead / 4 behind `master`** (per
`git rev-list --left-right --count master...HEAD`).
**Working tree:** clean. P1-A (`9c16122`), P1-B (`feat(paper): require approved execution
and client order ids`), P1-C (`fix(paper): serialize ledger writers with an advisory
lock`), and P1.4 (the head commit) are committed and **not pushed**. Do not reset, clean,
or push unless the user explicitly asks.

This is the fresh-session handoff. Read it fully before editing. It records what is done,
what was verified, the behavior contracts that must not regress, the remaining defects, and
the recommended order of work.

---

## 0. TL;DR

P0 safety is committed and green:

1. Auth is required on every non-public route.
2. There is one live-order path; live trading is paper-only by default.
3. The kill switch is fail-closed and requires human re-arm.
4. The free-model roster has a universal fallback.
5. Paper accounting has commissions, adverse slippage, mark-to-market, short
   proceeds/margin, and equity-based PnL.
6. Production Compose overlays activate the fail-fast secret validator.
7. Consensus requires **strictly greater than 80%**.

P1-A is committed as `9c16122`:

- PostgreSQL is the durable paper ledger (`paper_trading/repository.py`).
- `PaperTradingLedger` (`paper_trading/ledger.py`) coordinates the in-memory engine
  cache with one-transaction writes and cache rollback on failure.
- The API, paper worker, and runner use the ledger.
- `positions.side`, entry/exit commissions, margin, and the equity curve are persisted.
- The migration chain is tracked and has one head; schema/init copies are identical.
- A unit restart test and a manual PostgreSQL 16 execute → restart → stop-loss →
  restart round-trip pass.

P1-B is committed as `feat(paper): require approved execution and client order ids`:

- `/execute` is approved-only: it requires typed Market Analyst, Quant, and Risk outputs
  plus a required `client_order_id`.
- The server re-runs consensus, checks Risk approval/score, derives price from the
  approved `current_price`, derives quantity from `risk.max_position_size`, and caps
  notional at 2% of paper equity.
- Duplicate `client_order_id` values return **409** and never create a second position.
- `orders.client_order_id` and partial unique index `uq_orders_client_order_id` are in
  schema/init and migration `0003_order_idempotency`.
- Real PostgreSQL 16 checks passed for fresh migration, P1-A schema → `stamp 0002` →
  `upgrade head`, and duplicate rejection before/after restart.

P1-C is committed as `fix(paper): serialize ledger writers with an advisory lock`:

- `PaperLedgerRepository.writer_lock()` holds a transaction-scoped PostgreSQL advisory
  lock (`pg_try_advisory_xact_lock`) across hydrate → mutate → persist.
- `PaperTradingLedger` also takes an in-process `asyncio.Lock` around every cache
  operation, so a reader cannot re-hydrate mid-write.
- A writer that waits longer than `paper_trading_writer_lock_timeout_seconds` (10 s)
  raises `PaperLedgerBusyError`; `/execute` returns **503** with `Retry-After: 1`.
- No schema change, no migration. Real PostgreSQL 16 check passed for concurrent fills,
  duplicate client IDs, a held lock, lock release, and a cancelled writer.

P1.4 is committed as `test(paper): run the ledger suite against real PostgreSQL in CI`:
`tests/test_postgres_integration.py` runs the
hydrate → fill → restart → close path plus duplicate, concurrent-writer, and busy-lock
cases against a real database, and `.github/workflows/ci.yml::postgres-integration` runs it
on `postgres:16-alpine`. The module skips without `ARES_TEST_POSTGRES_URL`; CI sets
`ARES_REQUIRE_POSTGRES_INTEGRATION=1` so it cannot skip silently. The next work is **P1.6
role-based authorization**, then **P1.5 health/metrics**. Run the Phase 1 exit criterion
against a Compose stack before claiming Phase 1 done.

**Do not start new feature work before reading sections 2, 3, 5, 5a, 6, and 8.**

---

## 1. Fresh-session start checklist

Run these first from the repository root:

```powershell
cd C:\Users\ASUS\ares-ai
git branch --show-current
git status --short
git rev-list --left-right --count master...HEAD
```

Read in this order:

1. `AGENTS.md` — routing only.
2. `docs/01-SPEC.md` — the mandate and hard rules.
3. `docs/02-STATUS.md` — verified state and known gaps.
4. `docs/05-NEXT.md` — ordered plan.
5. `docs/03-ARCHITECTURE.md` — layers/data ownership.
6. `docs/04-DECISIONS.md` — ADRs (ADR-005 paper ledger, ADR-014 approved `/execute`).
7. This file.
8. The relevant folder `CONTEXT.md` before editing that folder.

Useful paths:

| Area | Read | Edit |
|---|---|---|
| Paper ledger | `paper_trading/CONTEXT.md` | `paper_trading/engine.py`, `repository.py`, `ledger.py`, `worker.py` |
| Execution | `agents/CONTEXT.md` | `agents/execution.py` |
| API | `backend/CONTEXT.md` | `backend/routers/trading.py`, `backend/schemas/trading.py`, `backend/main.py` |
| Config | `configs/CONTEXT.md` | `configs/settings.py`, `.env.example` |
| Live safety | `live_trading/CONTEXT.md` | `live_trading/engine.py`, `live_trading/safety.py` |
| Schema | `database/CONTEXT.md`, `migrations/CONTEXT.md` | `database/schema.sql`, `init.sql`, `migrations/versions/` |
| Tests | `tests/CONTEXT.md` | `tests/**` |
| Deployment | `docker/CONTEXT.md` | `docker-compose.yml`, production overlays |

Baseline checks:

```powershell
python -m pytest tests/ -q
ruff check .
ruff format --check .
mypy .
```

Expected today:

- `pytest`: **1103 passed**, 2 warnings, **80.08%** coverage, exit 0.
- `ruff check .`: clean.
- `ruff format --check .`: clean.
- `mypy .`: **22 pre-existing errors in 8 test/script files**. The six P1-B production
  modules are clean. Do not claim full mypy is green until those 22 are fixed.

Frontend (only needed for frontend changes):

```powershell
cd frontend
pnpm build
```

`pnpm build` passes (Next 16.2.12). `pnpm lint` currently fails because the script is
`next lint`, which Next 16 rejects as a directory. This is pre-existing; fix it as part of
frontend/CI work.

**Security trap:** do **not** run plain `docker compose config` in a captured terminal.
It can print local `.env` secrets. Use `config --quiet` with temporary dummy environment
values and do not print the resolved config.

---

## 2. Non-negotiable rules

These come from `AGENTS.md`, `docs/01-SPEC.md`, and the user's instructions.

1. **Free-tier models only.** Model IDs live only in `configs/models.yaml`, never
   hardcoded in agents.
2. **Every agent input/output is typed** with Pydantic; `rationale` is required wherever
   a trading number is produced.
3. **No signal = no trade.** A required agent failure rejects the trade; it never
   silently approves.
4. **Market Analyst and Quant must both be strictly above 80% confidence**, directions
   must agree, Risk must approve, and drawdown/exposure must be safe.
5. **Live trading starts in human-approval mode.** Autonomous mode is opt-in per
   strategy only after the paper-trading promotion gate.
6. **A kill switch must halt order placement and require human re-arm.** Never bypass a
   safety gate.
7. **Never hardcode or commit secrets.** `.env.example` only; `.env` stays untracked.
8. **Model failure degrades gracefully** and is logged with the fallback used.
9. **Definition of done:** tests pass, `ruff` + `mypy` clean, docs updated in the same
   change.
10. **Never weaken a safety gate to make a test pass.**
11. **Do not modify** `C:\Users\ASUS\.claude\plugins` or `C:\Users\ASUS\.claude\skills`;
    read-only use is allowed.
12. **No real-capital live trading.** Live code stays gated; do not enable it.
13. **Do not commit/push** unless the user explicitly asks. P1-A and P1-B are already
    committed; the branch is not pushed.
14. User preference: dashboard is single-user/local. Future market data direction is the
   existing ingestion + Binance WebSocket + Alpaca.
15. Use ICM/MVC structure and React/frontend review skills for frontend work.

---

## 3. Current verified state

### 3.1 Branch / worktree

- Branch: `fix/orchestration-reliability-frontend`
- 7 ahead / 4 behind `master`.
- Head: the P1.4 commit `test(paper): run the ledger suite against real PostgreSQL in CI`
  (the hash changes if the commit is amended; prefer `git log -1 --oneline`)
- P1-A is committed as `9c16122`, P1-B as `feat(paper): require approved execution and
  client order ids`, and P1-C as `fix(paper): serialize ledger writers with an advisory
  lock`. P1-C touches
  `paper_trading/repository.py`, `paper_trading/ledger.py`,
  `paper_trading/worker.py`, `backend/routers/trading.py`, `configs/settings.py`,
  `.env.example`, `tests/test_paper_trading_ledger.py`,
  `tests/test_paper_trading_worker.py`, `tests/test_trading_router.py`,
  `tests/test_config.py`, and the docs/context updates.
- P1.4 is committed as the head commit and touches `tests/test_postgres_integration.py`,
  `.github/workflows/ci.yml`, `tests/CONTEXT.md`, `docker/CONTEXT.md`,
  `docs/02-STATUS.md`, `docs/05-NEXT.md`, and this file.
- `migrations/versions/` is no longer gitignored and contains `.gitkeep`,
  `0001_initial_schema.py`, `0002_paper_ledger.py`, and `0003_order_idempotency.py`.
- No push, PR, or merge has been performed for P1-A, P1-B, P1-C, or P1.4.

### 3.2 Verified commands and results

| Check | Result |
|---|---|
| `python -m pytest tests/ -q` | **1103 passed, 1 skipped**, 2 warnings, exit 0 |
| Coverage | **80.08%** default / **80.10%** with the integration job, gate is 78% |
| `tests/test_paper_trading_ledger.py` | **34 passed** |
| `tests/test_trading_router.py` | **17 passed** |
| `tests/test_schema.py` | **15 passed** |
| `tests/test_paper_trading_worker.py` | **13 passed** |
| `tests/test_config.py` | **17 passed** |
| `tests/test_postgres_integration.py` (real PG) | **5 passed** |
| `ruff check .` | clean |
| `ruff format --check .` | clean |
| `mypy .` | **22 errors in 8 files**, all pre-existing tests/scripts |
| Targeted P1-B/P1-C mypy | clean on 5 production modules + `test_postgres_integration.py` |
| `python -m alembic heads` | **`0003_order_idempotency (head)`** |
| Frontend `pnpm build` | passed (P1-B wrapper update) |
| CI PostgreSQL job | `postgres-integration` added; not yet exercised on GitHub (branch not pushed) |
| Manual PostgreSQL 16 P1-B checks | passed on a temporary container; container removed |
| Manual PostgreSQL 16 P1-C checks | passed on a temporary container; container and script removed |

The 22 mypy errors are in:

- `tests/test_test_free_models.py` (6)
- `tests/test_error_handlers.py` (4)
- `tests/test_analysis_router.py` (3)
- `tests/test_paper_trading_worker.py` (3)
- `tests/test_supervisor.py` (2)
- `scripts/test_free_models.py` (2)
- `tests/test_live_trading/test_safety_edge_cases.py` (1)
- `tests/test_live_trading/test_engine_edge_cases.py` (1)

Do not report mypy as green. Do not add new production-code mypy errors while fixing
those.

### 3.3 Manual PostgreSQL evidence

**P1-A (committed):** A disposable PostgreSQL 16 container was started on port `55432`.
`alembic upgrade head` applied `0001` then `0002_paper_ledger`. An integration script then:

1. seeded a paper account/portfolio;
2. opened a long through `PaperTradingLedger`;
3. created a fresh engine, hydrated it, and verified the position;
4. processed a candle that hit the stop;
5. created another fresh engine and verified the closed trade persisted;
6. checked `trade_history` side/position_side/commissions/exit_reason and a 3-point
   equity curve;
7. opened a short, reversed it to long, and verified a third restart preserved one open
   long and two closed history rows with the correct position sides.

**P1-B (committed):** A fresh PostgreSQL 16 container on port `55433` was used:

1. Fresh `alembic upgrade head` produced `orders.client_order_id` and
   `uq_orders_client_order_id`; `alembic current` = `0003_order_idempotency`.
2. The P1-A schema (from `9c16122:database/schema.sql`) was loaded into an `ares_old`
   database, stamped `0002_paper_ledger`, then upgraded to head; the column/index were
   added.
3. Real ledger execution with `client_order_id="recheck-1"` created one order and one
   open position.
4. A duplicate request with the same client ID raised `PaperOrderConflictError`; a fresh
   process after restart also rejected it. One order and one open position remained.

The container, databases, and temporary scripts were removed. The user's real database
has **not** been migrated; run `alembic upgrade head` (or recreate it) before using this
build.

---

## 4. P1-A — durable paper ledger (committed)

### 4.1 New modules

**`paper_trading/repository.py` — `PaperLedgerRepository`**

- Loads the paper account/portfolio, open positions, closed trades, marks, and equity
  curve into the engine.
- Persists open positions, new entry orders, closed positions, `trade_history`, exit
  orders, and the portfolio in one transaction.
- Reads `positions.side`, `entry_commission`, `margin`, and
  `trade_history.position_side` / `entry_commission` / `exit_commission` /
  `exit_reason`.
- Raises `PaperLedgerError` on database failures. Returns `False` when no seeded paper
  account exists.

**`paper_trading/ledger.py` — `PaperTradingLedger`**

- `initialize()` / `refresh()` hydrate the cache.
- `execute_signal()` refreshes, snapshots, executes, persists, and rolls the cache back
  on failure.
- `process_candle()` refreshes, checks SL/TP, marks the remaining position, and
  persists both.
- If `repository.persist()` returns `False` (no seeded account), the cache is restored
  and the operation raises `PaperLedgerError`; an accepted trade is never left only in
  memory.
- Read helpers (`get_summary`, `get_open_positions`, `get_closed_trades`) refresh first.

### 4.2 Engine

`paper_trading/engine.py` gained:

- `PaperPosition.side`, `entry_commission`, `margin`.
- `ClosedTrade.position_id`, `exit_commission`, `exit_reason`.
- `snapshot()`, `restore_snapshot()`, `restore_state()`.
- `get_open_positions()`, `get_closed_trades()`, `get_equity_curve()`,
  `get_last_prices()`.
- Hydration preserves the engine's configured commission/slippage settings; fee
  configuration is **not** persisted in the portfolio. Every process must construct
  its engine with the same `paper_trading_commission_pct` /
  `paper_trading_slippage_pct` settings. The application factory does; direct callers
  must too.

### 4.3 API, worker, runner

- `backend/routers/trading.py`: process-local engine cache + `PaperTradingLedger`.
  `/portfolio`, `/positions`, `/orders` hydrate and return **503 Paper ledger
  unavailable** on `PaperLedgerError`. `/execute` goes through the ledger and returns
  `ledger_persisted=true`; no-seed writes become 503, not an in-memory success.
- `backend/main.py`: hydrates the ledger at startup and starts `PaperTradingWorker`
  with that ledger.
- `paper_trading/worker.py`: with a ledger, delegates each candle to
  `ledger.process_candle`; the raw-SQL fallback remains for direct-engine tests.
- `agents/execution.py`: paper execution uses the ledger when wired; direct SQL
  fallback remains for callers without a ledger.
- `scripts/run_live.py`: initializes and uses the ledger for candle processing.
- `backend/routers/analysis.py`: passes the shared ledger to `ExecutionAgent`.

### 4.4 Schema and migrations

P1-A columns:

- `positions.side`, `entry_commission`, `margin`
- `portfolio.initial_capital`, `margin_used`, `equity_curve`
- `trade_history.position_side`, `entry_commission`, `exit_commission`, `exit_reason`

`migrations/versions/0001_initial_schema.py` executes `database/schema.sql` through a
splitter that preserves single/double quotes and dollar-quoted PL/pgSQL. `0002` adds the
ledger columns and backfills `trade_history.position_side='short'` for sell entries.
Both follow-ups are idempotent because a fresh `0001` already executes the current schema.

`schema.sql` and `init.sql` are byte-identical after line-ending normalization;
`tests/test_schema.py` enforces it.

### 4.5 Tests added by P1-A

- `tests/test_paper_trading_ledger.py` — repository hydration, JSON curve, atomic
  writes, rollback, unseeded rejection, restart mid-trade.
- `tests/test_paper_trading_worker.py` — ledger-delegation test.
- `tests/test_execution_agent.py` — ledger path skips duplicate direct persistence.
- `tests/test_schema.py` — ledger columns, init/schema parity, dollar-quote splitter.

---

## 5. P1-B — approved execution + idempotency (committed)

### 5.1 Contract

`POST /api/v1/execute` accepts only:

```json
{
  "client_order_id": "order-123",
  "symbol": "BTC-USD",
  "side": "long",
  "approval": {
    "market_analyst_output": { "...": "typed MarketAnalystOutput" },
    "quant_output": { "...": "typed QuantOutput" },
    "risk_output": { "...": "typed RiskOutput" },
    "vision_output": null
  }
}
```

- `client_order_id` is required, 1–100 chars, `[A-Za-z0-9][A-Za-z0-9_.:-]*`.
- `side` is `long` or `short`.
- Unknown fields are rejected (`extra="forbid"`).
- There is **no** caller-supplied `quantity`, `entry_price`, `stop_loss`,
  `take_profit`, or `strategy_name`, and no manual bypass.

### 5.2 Validation in `backend/routers/trading.py`

The router:

1. Requires Market Analyst and Quant directions to equal the requested side.
2. Re-runs `ConsensusEngine.evaluate` from the typed outputs. Both confidences must be
   strictly >80 and directions must agree and be non-flat; Vision is an advisory nudge.
3. Requires `risk.approved=true` and `risk.risk_score <= 70`; rejects non-finite scores.
4. Derives `entry_price` from `market_analyst_output.indicators.current_price`; rejects
   missing, non-finite, or non-positive values.
5. Derives `quantity` from `risk.max_position_size`; rejects missing/non-finite/non-positive.
6. Uses `risk.stop_loss`; rejects non-finite/non-positive values and a long stop at or
   above entry or a short stop at or below entry.
7. Caps `quantity * entry_price` at **2% of current paper equity**
   (`MAX_POSITION_SIZE_PCT`), with a 0.1% rounding tolerance.
8. Calls `ledger.execute_signal(..., client_order_id=...)` and returns the result with
   `client_order_id` included.
9. Maps `PaperOrderConflictError` to **409**, `PaperLedgerError` to **503**, and
   validation failures to **422**.

The authenticated API key remains the trust boundary: a credential holder can supply
synthetic agent outputs. There is no signed/expiring signal token yet. Generated trades
continue through `/signal`.

### 5.3 Idempotency

- `orders.client_order_id VARCHAR(100)`.
- Partial unique index:
  `uq_orders_client_order_id ON orders(account_id, client_order_id) WHERE client_order_id IS NOT NULL`.
- `PaperLedgerRepository.client_order_id_exists()` pre-checks after hydration.
- `PaperTradingLedger.execute_signal()` checks before mutating the engine.
- `PaperOrderConflictError` is raised on the pre-check and when `IntegrityError` includes
  `client_order_id`.
- `PaperLedgerRepository.persist()` attaches the client ID to the **entry order only**;
  exit orders carry `None`.
- Duplicate requests return 409 and do not create a second order/position. They are not
  replayed as the original response.
- A failed/conflicting persist restores the hydrated cache snapshot.
- Pipeline-generated fills pass `client_order_id=None`; they are not idempotent.

### 5.4 Schema / migration

- `database/schema.sql` and `database/init.sql`: new column and partial unique index.
- `migrations/versions/0003_order_idempotency.py`: idempotent `ADD COLUMN IF NOT EXISTS`
  and `CREATE UNIQUE INDEX IF NOT EXISTS`.
- `backend/db/models.py`: `Order.client_order_id` and the matching index metadata.
- `backend/schemas/trading.py`: `OrderBase.client_order_id`, `TradeApproval`,
  `ExecuteTradeRequest`.

### 5.5 Tests / frontend

- `tests/test_trading_router.py` (16 tests): raw body rejected; approved long/short
  accepted; derived values passed to the ledger; low confidence, direction mismatch,
  risk rejection, high risk score, oversized notional, wrong-side stop, missing/non-finite
  price rejected; duplicate 409; ledger 503.
- `tests/test_paper_trading_ledger.py` (21 tests): duplicate pre-check, conflict mapping,
  client ID passed to persistence.
- `tests/test_schema.py` (15 tests): idempotency column/index and init/schema parity.
- `frontend/src/lib/api.ts::executeTrade` now sends the approved-only shape using
  `MarketAnalystOutput`, `QuantOutput`, `RiskOutput`, and optional `VisionOutput`.
  It is not called by any page; no UI bypass exists.

### 5.6 Real-DB result

Fresh `upgrade head` and P1-A schema → `stamp 0002_paper_ledger` → `upgrade head` both
produced the column/index. A duplicate `client_order_id` was rejected before and after
restart; exactly one order and one open position remained.

---

## 5a. P1-C — paper writer serialization (committed)

### 5a.1 Contract

Every paper-ledger write runs as:

1. `PaperTradingLedger` takes its in-process `asyncio.Lock` (covers the shared cache).
2. `PaperLedgerRepository.writer_lock(timeout_seconds=...)` acquires
   `pg_try_advisory_xact_lock(PAPER_LEDGER_WRITER_LOCK_KEY)` and holds the transaction.
3. hydrate → mutate the engine → `persist(...)` in one transaction.
4. Context exit rolls the lock transaction back, which releases the advisory lock.

`/execute` maps `PaperLedgerBusyError` to **503** with `Retry-After: 1`. A timeout mutates
nothing and leaves the cache untouched.

### 5a.2 Why transaction-scoped, not session-scoped

The first implementation used `pg_advisory_lock` + `pg_advisory_unlock`. Real PostgreSQL
showed the lock leaking: SQLAlchemy returns the connection to the pool on `COMMIT`, so the
unlock could run on a different pooled connection while the original backend stayed idle
holding the lock. `pg_advisory_xact_lock` is released by the rollback/close, so it cannot
outlive the operation. `pg_try_*` + polling keeps the wait bounded and surfaces busy state
instead of hanging.

### 5a.3 Code

- `paper_trading/repository.py`: `PAPER_LEDGER_WRITER_LOCK_KEY`,
  `WRITER_LOCK_POLL_INTERVAL_SECONDS`, `PaperLedgerBusyError`, `writer_lock`,
  `_acquire_writer_lock`.
- `paper_trading/ledger.py`: `_cache_lock`, `_hydrate`, `_execute_signal_locked`,
  `_process_candle_locked`, `get_open_position_symbols`; `writer_timeout_seconds`.
- `paper_trading/worker.py`: `_tick` now calls `ledger.get_open_position_symbols()`.
- `backend/routers/trading.py`: passes the configured timeout; 503 busy mapping.
- `configs/settings.py`, `.env.example`: `paper_trading_writer_lock_timeout_seconds=10.0`.

No schema, migration, or frontend change.

### 5a.4 Real-DB result (temporary PostgreSQL 16, port 55434)

1. Two concurrent fills (BTC long, ETH short) both persisted; 2 positions, 2 orders,
   cash exactly 78,000 with fees/slippage set to zero.
2. Two concurrent requests with the same `client_order_id`: exactly one accepted, one
   `PaperOrderConflictError`, 1 position and 1 order.
3. A separate connection held the advisory lock: `execute_signal` raised
   `PaperLedgerBusyError` within the 0.5 s timeout with no rows written; after release the
   retry succeeded.
4. A cancelled writer task released the lock (immediate re-acquire).
5. `pg_locks` showed zero advisory locks afterwards; the container and script were removed.

### 5a.5 Not covered

- The lock is per database, not per paper account.
- Reads skip the advisory lock (each process has its own cache); only the in-process lock
  guards them.
- The Compose restart exit check (Phase 1 exit) is still manual; P1.4 covers the database
  cases described in section 5b.

## 5b. P1.4 — real-PostgreSQL integration job (committed)

`tests/test_postgres_integration.py` is opt-in: it runs only when
`ARES_TEST_POSTGRES_URL` is set, and the module refuses a database whose name does not
contain `test`. Setup seeds one paper account and truncates only the ledger tables.

Covered on a real PostgreSQL 16 instance:

1. **Exit path:** fill BTC long at 50 000 → new process hydrates the position and 50 000
   cash → take-profit at 55 000 → third process sees the closed trade (+5 000), 105 000
   cash, `positions.is_open=false`, one `trade_history` row, and entry/exit orders.
2. **Duplicate after restart:** the same `client_order_id` raises
   `PaperOrderConflictError` before mutation; one order and one position remain.
3. **Concurrent distinct fills:** BTC long and ETH short from separate engines both
   persist; 2 positions, 2 orders, 52 000 cash.
4. **Concurrent duplicate:** exactly one accepted, one conflict, one order/one position.
5. **Busy writer:** while one connection holds the advisory lock, a 0.2 s-timeout writer
   gets `PaperLedgerBusyError` and writes nothing; after release the retry succeeds.

CI job `postgres-integration` (`.github/workflows/ci.yml`) starts `postgres:16-alpine`,
loads `database/schema.sql`, and runs the module with `--no-cov`. It sets
`ARES_REQUIRE_POSTGRES_INTEGRATION=1`, so a missing `ARES_TEST_POSTGRES_URL` is a hard
failure rather than a silent skip. Local numbers: 5 passed in ~5.2 s; the full suite is
**1108 passed / 80.10%** with the URL and **1103 passed + 1 skipped / 80.08%** without.

---

## 6. Behavior contracts that must not regress

### 6.1 Paper ledger

- PostgreSQL is the source of truth; the engine is a cache.
- Refresh before every action; snapshot before mutation; restore on failure **and on
  rejection**, so a failed reversal cannot leave the old position closed in the cache.
- A fill/mark/closure is one transaction across positions, orders, trade history, and
  portfolio.
- An accepted fill with no seeded paper account is rejected, not kept in memory.
- `PaperLedgerError` at the API boundary is a **503**, not a silent empty response.
- Fee/slippage settings are application configuration. Hydration does not persist or
  restore them; construct the engine with the configured values in every process.

### 6.2 Paper engine

- Direct `PaperTradingEngine()` defaults: `commission_pct=0.0`, `slippage_pct=0.0`.
- Application engine: `0.001` commission and `0.001` slippage.
- `total_pnl` is equity-based, not closed-trade-only.
- Shorts credit proceeds, report 100% notional margin, and subtract the liability from
  equity.
- A candle that hits both SL and TP resolves to **stop-loss first**.
- `mark_to_market` appends equity; `check_sl_tp` closes at the threshold and applies
  exit slippage/commission.
- `close_position` removes the position, updates cash/equity, and appends a
  `ClosedTrade`.

### 6.3 Paper worker / DB

- The worker checks exits before marking.
- With a ledger, the worker delegates to `process_candle`; it does not duplicate raw
  SQL persistence.
- The raw-SQL fallback is only for callers without a ledger.
- `trade_history.side` is constrained to `buy`/`sell`; `position_side` is
  `long`/`short`. Do not mix them.
- `orders` has no `strategy_name` or `reason`; use `agent_rationale` JSONB.
- `paper_trades` exists but is unused; promotion reads `trade_history`.
- `positions.side` exists; old notes saying it does not are stale.

### 6.4 API / execution

- `/api/v1/execute` is approved-only. A request without a valid `approval` object cannot
  create a position. Do not reintroduce raw quantity/price fields or a manual bypass.
- The server derives fill price and quantity; do not trust caller-supplied trading
  numbers.
- `client_order_id` is required on `/execute`. Duplicate IDs are **409**, never a second
  position.
- `agents/execution.py` must report the engine's actual fill and quantity, not the
  requested signal.
- Live execution must continue through `LiveTradingEngine.execute_signal` only.

### 6.5 Consensus / risk

- Market Analyst **> 80%**.
- Quant **> 80%**.
- Directions agree and are non-flat.
- Risk approves; risk score must stay within the agent limit (70).
- Exactly 80.0% is not enough.
- `/execute` re-runs these checks; it never trusts a caller's `approved` boolean.

### 6.6 Production

- Production uses an explicit Compose overlay.
- Base development Compose files do not set `ENVIRONMENT=production`.
- The overlay does not enable live trading.
- Do not put secrets in Compose files or docs.

---

## 7. Known gaps — exact next targets

### Gap 1 — Concurrent paper writers — closed by P1-C

- Fixed by `PaperLedgerRepository.writer_lock()` (transaction-scoped advisory lock) plus
  the ledger's in-process `asyncio.Lock`.
- Copy the pattern if another mutable domain cache is added; do not reintroduce a
  refresh-then-write cycle outside these locks.
- Remaining: no automated PostgreSQL test (see Gap 7).

### Gap 2 — Approved `/execute` trust boundary (P2)

- The route re-runs consensus/risk and caps size, but the authenticated caller supplies
  the agent outputs.
- No signed/expiring approval token or server-side signal record is required.
- The API key remains the operator trust boundary. A future design should bind execution
  to a stored `signals` row or a signed nonce with an expiry.

### Gap 3 — No role-based authorization on trading/live routes (P1)

- Any valid API key or JWT reaches live controls.
- Require operator/admin for `/live/start`, `/live/kill`, `/live/arm`, mode changes,
  and trading controls; add viewer/operator/admin route tests.

### Gap 4 — `mypy` red (P1 CI)

- 22 errors in 8 test/script files (list in section 3.2).
- P1-B/P1-C production modules are clean.
- Fix these before calling CI green; then add mypy to CI.

### Gap 5 — `/analyze` concurrency/cost control (P1)

- Global `_last_state`; unbounded `BackgroundTasks`; runs are not isolated.
- Add per-run IDs, a semaphore/queue, timeouts, cancellation, and a cost budget.

### Gap 6 — Kill-switch latch is process-local (P1 operational)

- A Redis outage latches each process.
- `/live/arm` clears the API process, but a runner that also latched stays blocked until
  restarted.
- Fail-closed and safe, but operationally awkward.
- Implement a shared Redis arm epoch/generation and test multi-process recovery.

### Gap 7 — PostgreSQL integration in CI — closed by P1.4

- `tests/test_postgres_integration.py` + the `postgres-integration` job cover hydrate →
  fill → restart → close, duplicate IDs, concurrent fills, the duplicate race, and the
  busy lock on `postgres:16-alpine`.
- Not covered: restarting a Compose stack mid-trade (Phase 1 exit).

### Gap 8 — Old short positions migration (P1 operational)

- Pre-P1-A `positions` rows have no direction; `0002` assumes long.
- Reconcile any historical short positions manually before relying on their records.

### Gap 9 — Frontend mock data / lint (P2)

- `frontend/src/app/markets/page.tsx` uses `Math.random()` candles.
- `settings/page.tsx` does not persist through the API and shows fake values.
- `pnpm lint` fails because `next lint` is invalid under Next 16.

### Gap 10 — Model catalog CI (P2)

- `scripts/test_free_models.py` exists but is manual.
- Add a scheduled/CI catalog-validation job.

### Gap 11 — Paper realism beyond P1-A (P2)

Current model still has:

- stop fills at the stop price even if the candle gapped through it,
- no partial fills/liquidity,
- no borrow/funding cost for shorts,
- one global slippage setting.

These are acceptable for the current milestone but must be documented before claiming
high-fidelity paper results.

---

## 8. Recommended next work, in order

### P1-C — Concurrent writer safety — done

- Implemented: transaction-scoped advisory lock + in-process cache lock.
- Preserve `client_order_id` idempotency and the approved-only `/execute` gate.
- Do not replace the lock with a session-level advisory lock (it leaks via the pool).

### P1-D — PostgreSQL CI and type/CI hygiene — P1.4 done, mypy pending

- P1.4 is committed as the head commit: see section 5b.
- Fix the 22 mypy errors; the existing `lint` job runs `mypy .`, so it stays red until
  they are fixed.
- Keep production modules clean.

### P1-E — Authorization and kill-switch operations

- Add roles to users/JWT/API-key mapping.
- Require operator/admin for live controls.
- Add a shared Redis arm epoch so one human re-arm clears all processes.

### P2 — Paper realism, frontend, observability

- Pass candle open into `check_sl_tp` for gap-through stops.
- Per-symbol/asset commission and slippage; borrow/funding costs; partial fills.
- Replace mock market/settings pages; persist settings through the API.
- Replace global `_last_state`; add bounded analysis runs and metrics/alerts.

---

## 9. Exact verification commands

Run from the repository root unless noted.

```powershell
# Full suite
python -m pytest tests/ -q

# Focused paper/ledger/schema/route tests
python -m pytest tests/test_paper_trading.py tests/test_paper_trading_ledger.py `
  tests/test_paper_trading_worker.py tests/test_execution_agent.py `
  tests/test_trading_router.py tests/test_schema.py -q --no-cov

# Lint/format
ruff check .
ruff format --check .

# Type checks (expected 22 test/script errors today)
mypy .

# Targeted P1-B/P1-C production check (should be clean)
mypy backend/routers/trading.py backend/schemas/trading.py backend/db/models.py `
  paper_trading/repository.py paper_trading/ledger.py paper_trading/worker.py `
  configs/settings.py migrations/versions/0003_order_idempotency.py

# Integration test typing (should be clean)
mypy tests/test_postgres_integration.py

# Real-PostgreSQL integration (disposable DB; module skips without the URL)
$env:ARES_TEST_POSTGRES_URL='postgresql+asyncpg://ares:ares_test@localhost:5432/ares_ai_test'
python -m pytest tests/test_postgres_integration.py -q --no-cov

# Alembic
python -m alembic heads
python -m alembic history
# On a scratch PostgreSQL 16 database:
# $env:DATABASE_URL='postgresql+asyncpg://...'
# python -m alembic upgrade head

# Frontend
cd frontend
pnpm build
cd ..

# Compose overlay validation (dummy values; keep output quiet)
$env:API_SECRET_KEY='test-only-key'
$env:POSTGRES_PASSWORD='test-only-db'
$env:JWT_SECRET_KEY='test-only-jwt'
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
```

Do not run the Compose command without dummy values if the resolved output could be
captured; `.env` may contain live keys.

---

## 10. Traps and gotchas

1. **Do not use a naive semicolon splitter for `schema.sql`.** The trigger function
   contains dollar-quoted `$$` and internal semicolons. Use the `_split_sql()` in
   `0001_initial_schema.py` and keep its regression test.
2. **`schema.sql` and `init.sql` must stay byte-identical** after line-ending
   normalization. A schema change updates both and a migration.
3. **`0001` executes the current schema.** Follow-up revisions must be idempotent
   (`IF NOT EXISTS` / guarded constraints) or a fresh `alembic upgrade head` fails.
   This applies to `0003`.
4. **Do not reset a user's database.** Existing deployments need
   `alembic upgrade head`; `init.sql` only runs on first container start.
5. **Fee configuration is not persisted.** Construct every process engine with the same
   settings; otherwise a restart silently changes fill costs.
6. **`PaperLedgerError` must become 503 at the API boundary.** Do not swallow it into an
   empty portfolio or a 200 response.
7. **A no-seed ledger rejects writes.** `initialize()` may still return `False` and the
   API may serve empty read state, but `/execute` and candle marks cannot be left
   in-memory.
8. **Mocked sessions do not validate SQL columns.** Real Postgres caught the original
   dollar-quote splitter failure and would catch future column drift.
9. **`trade_history.side` is `buy`/`sell`; `position_side` is `long`/`short`.** Map at
   the persistence boundary.
10. **`positions.side` now exists.** Old notes saying it does not are stale. Old rows
    default to long.
11. **`paper_trades` is unused.** Promotion reads `trade_history`.
12. **The stop-first policy is deliberate.** Do not revert to TP-first; it inflates
    paper results.
13. **Consensus exactly 80% is rejected.** Do not change back to `>=`.
14. **The API and runner are separate processes.** A module singleton is per process;
    PostgreSQL is the shared state.
15. **Paper writers must take the locks.** `execute_signal`, `process_candle`, and any
    read that hydrates the shared engine go through `PaperTradingLedger`, which holds the
    cache lock and (for writes) the repository writer lock. Do not add a
    refresh-then-write path that bypasses them.
16. **Never use a session-level advisory lock (`pg_advisory_lock`) for the ledger.**
    SQLAlchemy returns the connection to the pool on `COMMIT`, so the unlock can land on a
    different connection and the lock leaks on an idle backend. Real PostgreSQL 16
    reproduced this: the next writer blocked forever. Use `pg_try_advisory_xact_lock` and
    let the context-manager rollback release it.
17. **`/execute` has no manual path.** It requires approvals. Do not add a raw body or a
    `manual=true` shortcut without a separately designed label and promotion exclusion.
18. **The client order ID belongs to the entry order only.** Exit orders must keep
    `client_order_id=None`; the partial unique index is per request, not per leg.
19. **Reject non-finite numbers.** The route checks `math.isfinite` for price, quantity,
    stop, risk score, equity, and notional. Do not remove those checks.
20. **`pnpm lint` is broken by the Next 16 migration.** `pnpm build` passes; fix the
    script separately.
21. **Never print resolved Compose output** or commit `.env`.

---

## 11. Definition of done for the next session

A change is not finished until:

- the focused tests pass first,
- `pytest tests/ -q` passes (current baseline 1103),
- coverage stays at or above 78%,
- `ruff check .` and `ruff format --check .` are clean,
- `mypy` has no new errors (ideally all 22 are fixed if claiming CI green),
- a real PostgreSQL migration/round-trip is run for schema/ledger changes,
- frontend `pnpm build` passes for frontend changes,
- docs and the routed `CONTEXT.md` are updated,
- `docs/02-STATUS.md` is updated with verified numbers, not estimates,
- no safety gate was weakened,
- no secrets are added to tracked files,
- no commit/push is made unless the user explicitly asks.

---

## 12. Handoff summary in one paragraph

P0 safety is committed and verified. P1-A is committed as `9c16122`: PostgreSQL is the
durable paper ledger, `PaperTradingLedger` hydrates the engine cache and writes each
fill/mark/closure in one transaction with rollback, the API/worker/runner use it, and
`positions.side` plus cost/margin/equity fields are persisted. P1-B is committed as
`feat(paper): require approved execution and client order ids`: `/execute` requires typed
Market Analyst/Quant/Risk approvals, re-runs consensus, derives price/size, caps notional
at 2% of equity, and rejects duplicate `client_order_id`s with 409;
`orders.client_order_id` plus a partial unique index and migration `0003` back it. P1-C is
committed as `fix(paper): serialize ledger writers with an advisory lock`: every paper write
takes an in-process cache lock plus a transaction-scoped PostgreSQL advisory lock
(`pg_try_advisory_xact_lock`) across hydrate → mutate → persist, so API, worker, and runner
serialize instead of losing updates; a writer that cannot get the lock within 10 s gets 503
with `Retry-After: 1`. P1.4 is committed as
`test(paper): run the ledger suite against real PostgreSQL in CI`:
`tests/test_postgres_integration.py` proves hydrate → fill → restart → close, duplicate
IDs, concurrent fills, the one-winner duplicate race, and the busy lock on real PostgreSQL
16, and the `postgres-integration` CI job runs it on `postgres:16-alpine`.
Verification today is **1103 passed + 1 skipped / 80.08% coverage** without a database and
**1108 passed / 80.10%** with one, clean ruff, 22 pre-existing mypy errors in tests/scripts,
a passing frontend build, and real PostgreSQL 16 checks for fresh
migration, P1-A → `0002` → head, duplicate rejection before/after restart, concurrent
fills, a held lock, lock release, and a cancelled writer. The next change is **P1.6 role
authorization**, then **P1.5 health/metrics**; run the Phase 1 exit criterion against a
Compose stack before calling Phase 1 done. The branch is not pushed. Do not push, reset, or
rewrite history without explicit user approval.
