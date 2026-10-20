<!-- paper_trading/CONTEXT.md -->
# paper_trading/ — contract

**Purpose:** simulated fills and portfolio accounting. No LLM, no exchange.

## Files
- `engine.py` — `PaperTradingEngine`, `PaperPosition`, `ClosedTrade`, `PortfolioSummary`.
- `worker.py` — polling loop that checks stop-loss/take-profit on incoming candles.

## Inputs
- Approved signal: symbol, side, quantity, price.
- Candles for marks and SL/TP checks.
- `paper_trading_initial_capital`, `paper_trading_commission_pct`, and
  `paper_trading_slippage_pct` from settings. The application engine uses 10 bps
  each by default; direct engine construction defaults to zero for unit tests.

## Process
1. `execute_signal` closes an opposite position if present, applies adverse
   slippage, sizes against cash (long) or equity with 100% short margin, records
   the position, and debits/credits cash including entry commission.
2. `mark_to_market` updates the latest price and appends equity on every bar;
   `check_sl_tp` closes on threshold (stop first when a candle spans both levels);
   `close_position` applies exit slippage and commission, computes net PnL, and
   appends equity.
3. `get_summary` returns cash, equity, margin used, all-in PnL, return %, win
   rate, and drawdown from the equity curve.

## Outputs
In-memory positions/trades/summary. `agents/execution.py` persists a `positions`
row and reversal `trade_history`; `worker.py` persists SL/TP closures and mirrors
the engine's portfolio snapshot into the DB.

## Invariants
- Fills apply configured commission and adverse slippage.
- Equity marks open positions at the latest price; `total_pnl = equity - initial`.
- Shorts credit proceeds, report 100% notional margin, and subtract the liability
  from equity. Cash and reported PnL reconcile after every fill.
- One engine instance per process is a cache, not a durable source of truth
  (ADR-005).

## Human check
`GET /api/v1/portfolio`, `/positions`, `/orders`; promotion gate reads
`trade_history` and the portfolio drawdown projection.

## Tests
`tests/test_paper_trading.py`, `tests/test_paper_trading_worker.py`,
`tests/test_execution_agent.py`.

## Known gaps
In-memory state resets on restart. The DB `positions` table has no long/short
column, so short positions are projected as unsigned rows. The portfolio row is a
projection of the engine until the P1 single-source migration.
