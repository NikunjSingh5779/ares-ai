<!-- docs/map/objects/portfolio.md -->
# Portfolio, position, order, paper record

**What it is:** the paper money state. PostgreSQL (`portfolio`, `positions`, `orders`,
`trade_history`) is durable; the in-memory `PaperTradingEngine` is a hydrated cache.
`paper_trades` exists but is unused; promotion reads `trade_history`.

**Homes:**
- `paper_trading/engine.py` — `PaperPosition`, `ClosedTrade`, `PortfolioSummary`,
  cash, equity, marks, commissions, margin, snapshot/restore.
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
take_profit, entry_commission, margin}`; closed trade adds `exit_price`, `pnl`,
`pnl_pct`, `entry_commission`, `exit_commission`, `exit_reason`; summary adds cash,
equity, `margin_used`, return %, win rate, max drawdown.

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
slippage apply; a candle spanning both levels resolves to the stop;
`total_pnl = equity - initial_capital`; shorts carry side/margin explicitly. The API
cannot supply its own price or quantity, and a duplicate `client_order_id` returns 409
before a second position is created.

**Change impact:**
- Add a field → DB column + migration + Pydantic model + `to_dict` + frontend type + tests.
- Change fill logic → `paper_trading/engine.py`, fee/slippage tests, promotion thresholds.
- Change persistence → `repository.py`, `ledger.py`, `worker.py`, `run_live.py`, schema.
- Change lock scope or timeout → `repository.py::writer_lock`, `paper_trading_writer_lock_timeout_seconds`,
  ADR-015, ledger tests; keep the writer paths (execute, candle, worker) inside the lock.

**Tests:** `tests/test_paper_trading.py`, `tests/test_paper_trading_ledger.py`,
`tests/test_paper_trading_worker.py`, `tests/test_execution_agent.py`,
`tests/test_trading_router.py`, `tests/test_schema.py`.

**Known gaps:** the advisory lock is database-wide rather than per account (fine at
single-user scale); reads do not take it because each process has its own cache. `/execute`
requires a signed, expiring approval token from `/signal`; the token is not single-use, so
`client_order_id` remains the duplicate-order guard. Old short **positions** cannot be inferred
during migration and default to long.
