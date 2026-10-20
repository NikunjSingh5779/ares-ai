<!-- docs/map/objects/portfolio.md -->
# Portfolio, position, order, paper record

**What it is:** the money state. In code it is an in-memory `PaperTradingEngine`; in
the database it is the `portfolio`, `positions`, `orders`, `trade_history`, and
(unused) `paper_trades` tables. These are currently **two sources of truth** (ADR-005);
the DB portfolio row is a projection of the engine.

**Homes:**
- `paper_trading/engine.py` — `PaperPosition`, `ClosedTrade`, `PortfolioSummary`,
  cash, equity, marks, commissions, margin.
- `paper_trading/worker.py` — SL/TP polling, per-candle marks, DB projection.
- `backend/routers/trading.py` — module-global engine singleton + `/portfolio`,
  `/positions`, `/orders`, `/execute`.
- `database/schema.sql` — the tables above; `positions` has no side column.

**Shape:** position = `{id, symbol, side, quantity, entry_price, entry_at, stop_loss,
take_profit, entry_commission, margin}`; closed trade adds `exit_price`, `pnl`,
`pnl_pct`, `entry_commission`, `exit_commission`; summary adds cash, equity,
`margin_used`, return %, win rate, max drawdown.

**Writers:** `PaperTradingEngine.execute_signal`, `close_position`, `check_sl_tp`,
`mark_to_market`; `agents/execution.py` persists the actual fill/quantity via raw SQL;
`paper_trading/worker.py` persists SL/TP closures and mirrors the portfolio row. The
runner process has its own engine instance.

**Readers:** `/api/v1/portfolio`, `/positions`, `/orders`; promotion gate
(`live_trading/engine.py` queries `trade_history` and portfolio drawdown); frontend
portfolio/paper pages.

**Invariants:** one writer per fact is the target; a fill updates cash, position, and
trade atomically; equity marks open positions at the latest price; configured fees and
adverse slippage apply; a candle spanning both levels resolves to the stop;
`total_pnl = equity - initial_capital`.

**Change impact:**
- Add a field → DB column + Pydantic model + `to_dict` + frontend type + tests.
- Change fill logic → `paper_trading/engine.py`, fee/slippage tests, promotion thresholds.
- Move to persistence → ADR-005, `backend/routers/trading.py`, `worker.py`, `run_live.py`.

**Tests:** `tests/test_paper_trading.py`, `tests/test_paper_trading_worker.py`,
`tests/test_execution_agent.py`, `tests/test_config.py`.

**Known gaps:** restart resets capital; DB `positions` cannot represent short/long;
the worker only syncs the portfolio row when it closes a trade; `/execute` has no risk
check. `paper_trades` exists but is unused; promotion reads `trade_history`.
