<!-- docs/map/objects/portfolio.md -->
# Portfolio, position, order, paper record

**What it is:** the paper money state. PostgreSQL (`portfolio`, `positions`, `orders`,
`trade_history`) is durable; the in-memory `PaperTradingEngine` is a hydrated cache.
`paper_trades` exists but is unused; promotion reads `trade_history`.

**Homes:**
- `paper_trading/engine.py` — `PaperPosition`, `ClosedTrade`, `PortfolioSummary`,
  cash, equity, marks, commissions, margin, borrow/funding carry, snapshot/restore.
- `paper_trading/repository.py` — `PaperLedgerRepository`; hydration, one-transaction
  writes for portfolio/positions/orders/history, and `writer_lock()` (transaction-scoped
  PostgreSQL advisory lock that serializes API/worker/runner writers).
- `paper_trading/ledger.py` — `PaperTradingLedger`; refresh → mutate → persist under an
  in-process cache lock and the repository writer lock, with cache rollback on failure.
- `paper_trading/worker.py` — SL/TP polling; delegates candle processing to the ledger.
- `backend/routers/trading.py` — ledger factory + `/portfolio`, `/positions`, `/orders`,
  approved-only `/execute` with server-side consensus/risk checks and 2% notional cap.
- `backend/schemas/trading.py` — `ExecuteTradeRequest` and `TradeApproval`.
- `database/schema.sql` — the tables above, including `positions.side`, the paper
  cost/margin/equity fields, and `orders.client_order_id`.

**Shape:** position = `{id, symbol, side, quantity, entry_price, entry_at, stop_loss,
take_profit, entry_commission, margin, carry_cost, last_accrual_at, requested_quantity,
entry_order_status, entry_order_reason}` (the last three are in-memory only and are
never persisted); closed trade adds `exit_price`, `pnl`, `pnl_pct`, `entry_commission`,
`exit_commission`, `carry_cost`, `exit_reason`; summary adds cash, equity,
`margin_used`, `carry_cost`, return %, win rate, max drawdown.

**Writers:** `PaperTradingLedger.execute_signal` / `process_candle`; `agents/execution.py`
uses the ledger for paper fills (direct-SQL fallback only when no ledger is wired);
`paper_trading/worker.py` delegates closures and marks. `/execute` accepts only typed
Market Analyst/Quant/Risk approvals, re-runs consensus, derives price/size, and requires a
`client_order_id`. API, worker, and runner each have a process-local engine cache but share
the same PostgreSQL ledger.

**Readers:** `/api/v1/portfolio`, `/positions`, `/orders` (hydrate first); promotion gate
(`live_trading/engine.py` queries `trade_history` and portfolio drawdown); frontend
portfolio/paper pages.

**Invariants:** one transaction per fill/mark/closure; writers serialize on the advisory
lock, so a second process waits for the first commit instead of overwriting it; cache
rollback on failure or
rejection (a failed reversal keeps the old position); an accepted fill with no seeded
paper account is rejected; configured fees and adverse
slippage apply (a per-symbol override replaces the global rate, otherwise the global
rate applies); annualized borrow (shorts) and funding (longs) accrue from
`last_accrual_at` on entry notional and are subtracted from equity while open; a
close accrues the final period and settles the total into cash and PnL; a timestamp
at or before the stored clock is ignored and a zero rate still advances it; a candle
spanning both levels resolves to the stop; a stop that gaps beyond its level fills at
the candle open; market orders are IOC and capped at the participation fraction of
candle volume (`partially_filled` is terminal, a missing/non-positive volume means no
cap); a partial close allocates entry commission and accrued carry to the closed lot
and leaves the remainder open with its stop and accrual clock; one `trade_history`
row is written per realized lot, so trade counts count lots, not positions;
`total_pnl = equity - initial_capital`; shorts carry side/margin
explicitly. The API cannot supply its own price or quantity, and a duplicate
`client_order_id` returns 409 before a second position is created.

**Change impact:**
- Add a field → DB column + migration + Pydantic model + `to_dict` + frontend type + tests.
- Change fill logic → `paper_trading/engine.py`, fee/slippage/carry/participation tests, promotion thresholds.
- Change persistence → `repository.py`, `ledger.py`, `worker.py`, `run_live.py`, schema.
- Change lock scope or timeout → `repository.py::writer_lock`, `paper_trading_writer_lock_timeout_seconds`,
  ADR-015, ledger tests; keep the writer paths (execute, candle, worker) inside the lock.

**Tests:** `tests/test_paper_trading.py`, `tests/test_paper_trading_ledger.py`,
`tests/test_paper_trading_worker.py`, `tests/test_execution_agent.py`,
`tests/test_trading_router.py`, `tests/test_schema.py`,
`tests/test_postgres_integration.py`.

**Known gaps:** the advisory lock is database-wide rather than per account (fine at
single-user scale); reads do not take it because each process has its own cache. `/execute`
requires a signed, expiring approval token from `/signal`; the token is not single-use, so
`client_order_id` remains the duplicate-order guard. Old short **positions** cannot be inferred
during migration and default to long. Liquidity is a hard participation cap on reported
candle volume, not a price-impact model; a partial entry is not retried (IOC is terminal).
Carry is charged on entry notional only (not mark-to-market notional), has no
funding credits, and legacy `agents/execution.py`/worker direct-SQL fallbacks bypass the
repository, so they do not persist carry.
