# CONTINUE.md — ARES AI handoff

**Last updated:** 2026-10-21
**Repository:** `C:\Users\ASUS\ares-ai`
**Branch:** `fix/orchestration-reliability-frontend`
**P1-B commit:** `feat(paper): require approved execution and client order ids` (read the
hash with `git log -1 --format=%h`).
**Branch position:** **5 commits ahead / 4 behind `master`** (per
`git rev-list --left-right --count master...HEAD`).
**Working tree:** clean. P1-A (`9c16122`) and P1-B (the commit above) are committed and
**not pushed**. Do not reset, clean, or push unless the user explicitly asks.

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

The next release blocker is **P1-C: concurrent paper-writer safety**. The engine is still
a process-local cache; API, worker, and runner can race and last-writer-wins. P1-B's
idempotency key prevents duplicate requests, not lost updates.

**Do not start new feature work before reading sections 2, 3, 5, and 7.**

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

- `pytest`: **1088 passed**, 2 warnings, **79.92%** coverage, exit 0.
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
- 5 ahead / 4 behind `master`
- Head: the P1-B commit `feat(paper): require approved execution and client order ids`
  (the hash changes if the commit is amended; prefer `git log -1 --oneline`)
- P1-A is committed as `9c16122` and P1-B as that commit; the working tree is clean.
  P1-B covers `backend/schemas/trading.py`, `backend/routers/trading.py`,
  `backend/db/models.py`, `paper_trading/repository.py`, `paper_trading/ledger.py`,
  `database/schema.sql`, `database/init.sql`,
  `migrations/versions/0003_order_idempotency.py`, `tests/test_paper_trading_ledger.py`,
  `tests/test_trading_router.py`, `tests/test_schema.py`, `frontend/src/lib/api.ts`, and
  the docs/context updates.
- `migrations/versions/` is no longer gitignored and contains `.gitkeep`,
  `0001_initial_schema.py`, `0002_paper_ledger.py`, and `0003_order_idempotency.py`.
- No push, PR, or merge has been performed for P1-A or P1-B.

### 3.2 Verified commands and results

| Check | Result |
|---|---|
| `python -m pytest tests/ -q` | **1088 passed**, 2 warnings, exit 0 |
| Coverage | **79.92%**, gate is 78% |
| `tests/test_paper_trading_ledger.py` | **21 passed** |
| `tests/test_trading_router.py` | **16 passed** |
| `tests/test_schema.py` | **15 passed** |
| `ruff check .` | clean |
| `ruff format --check .` | clean |
| `mypy .` | **22 errors in 8 files**, all pre-existing tests/scripts |
| Targeted P1-B mypy | clean on 6 production modules |
| `python -m alembic heads` | **`0003_order_idempotency (head)`** |
| Frontend `pnpm build` | passed (P1-B wrapper update) |
| Manual PostgreSQL 16 P1-B checks | passed on a temporary container; container removed |

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

### Gap 1 — Concurrent paper writers (P1-C, highest priority)

- API, worker, and runner each refresh then persist; there is no row lock, optimistic
  version, or command log.
- Simultaneous fills/marks are last-writer-wins and can lose an update.
- `client_order_id` closes duplicate-request races only; it does not make a fill and a
  mark serialize.
- Add row locking or a version column on the ledger/portfolio, or serialize through one
  writer with an idempotent command table.
- Test two concurrent writes to the same paper account.

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
- P1-B production modules are clean.
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

### Gap 7 — PostgreSQL integration in CI (P2)

- The real database round-trips are manual only.
- Add a Testcontainers/Compose-backed test job for hydrate → fill → restart → close,
  duplicate client IDs, and every SQL column referenced by worker/agent code.

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

### P1-C — Concurrent writer safety

- Add row locking/version checks or a single-writer command table.
- Test concurrent API + worker writes and verify no lost fill.
- Consider surfacing ledger version/revision in API responses.
- Keep `client_order_id` idempotency; do not weaken the approved-only `/execute` gate.

### P1-D — PostgreSQL CI and type/CI hygiene

- Add a Postgres-backed integration job, including duplicate client IDs and restart.
- Fix the 22 mypy errors; keep production modules clean.
- Add CI: pytest, ruff check, ruff format --check, mypy, frontend build, frontend lint
  after fixing the script.

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

# Targeted P1-B production check (should be clean)
mypy backend/routers/trading.py backend/schemas/trading.py backend/db/models.py `
  paper_trading/repository.py paper_trading/ledger.py `
  migrations/versions/0003_order_idempotency.py

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
15. **Concurrent writers are still unsafe.** `client_order_id` is not row locking. Do not
    claim P1 is complete until P1-C lands.
16. **`/execute` has no manual path.** It requires approvals. Do not add a raw body or a
    `manual=true` shortcut without a separately designed label and promotion exclusion.
17. **The client order ID belongs to the entry order only.** Exit orders must keep
    `client_order_id=None`; the partial unique index is per request, not per leg.
18. **Reject non-finite numbers.** The route checks `math.isfinite` for price, quantity,
    stop, risk score, equity, and notional. Do not remove those checks.
19. **`pnpm lint` is broken by the Next 16 migration.** `pnpm build` passes; fix the
    script separately.
20. **Never print resolved Compose output** or commit `.env`.

---

## 11. Definition of done for the next session

A change is not finished until:

- the focused tests pass first,
- `pytest tests/ -q` passes (current baseline 1088),
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
Market Analyst/Quant/Risk approvals, re-runs
consensus, derives price/size, caps notional at 2% of equity, and rejects duplicate
`client_order_id`s with 409; `orders.client_order_id` plus a partial unique index and
migration `0003` back it. Verification today is **1088 tests / 79.92% coverage**, clean
ruff, 22 pre-existing mypy errors in tests/scripts, a passing frontend build, and real
PostgreSQL 16 checks for fresh migration, P1-A → `0002` → head, and duplicate rejection
before/after restart. The next change is **P1-C: row locking or optimistic versions for
concurrent paper writers**, followed by PostgreSQL CI, role-based live authorization, and
the shared kill-switch arm epoch. The working tree is clean; the branch is not pushed. Do
not push, reset, or rewrite history without explicit user approval.
