<!-- paper_trading/CONTEXT.md -->
# paper_trading/ — contract

**Purpose:** simulated fills, portfolio accounting, and the durable paper ledger. No
LLM, no exchange.

## Files
- `engine.py` — `PaperTradingEngine`, `PaperPosition`, `ClosedTrade`,
  `PortfolioSummary`; snapshot/restore/hydration APIs.
- `repository.py` — `PaperLedgerRepository`; the only SQL reader/writer for the
  paper account, portfolio, open positions, orders, and closed-trade history.
- `ledger.py` — `PaperTradingLedger`; refreshes the cache, mutates the engine, writes
  one transaction, and restores the cache on failure.
- `worker.py` — polling loop that checks stop-loss/take-profit on incoming candles
  through the ledger.

## Inputs
- Approved signal: symbol, side, quantity, price.
- For API `/execute`, a typed approval payload plus `client_order_id`; the router derives
  quantity, price, and stop-loss before calling the ledger.
- Candles for marks and SL/TP checks.
- `paper_trading_initial_capital`, `paper_trading_commission_pct`, and
  `paper_trading_slippage_pct` from settings. The application constructs its engine
  with 10 bps each by default; direct engine construction defaults to zero for unit
  tests. Fee/slippage settings are configuration, not persisted state, so every
  process that hydrates the ledger must construct its engine with the same settings.

## Process
1. `PaperTradingLedger.execute_signal` refreshes from PostgreSQL, rejects an already-used
   `client_order_id`, snapshots the engine, closes an opposite position if present,
   applies adverse slippage, sizes against cash (long) or equity with 100% short margin,
   records the position, and debits/credits cash including entry commission. It persists
   the open position, entry order with its client ID, any reversal close/history, and
   portfolio in one transaction. Exit orders carry no client ID.
2. `PaperTradingLedger.process_candle` refreshes, checks SL/TP first (stop first when a
   candle spans both levels), marks any remaining open position, and persists the
   closure and/or mark.
3. `mark_to_market` updates the latest price and appends equity on every bar;
   `close_position` applies exit slippage and commission, computes net PnL, and appends
   equity.
4. `get_summary` returns cash, equity, margin used, all-in PnL, return %, win rate, and
   drawdown from the persisted equity curve.

## Outputs
Durable rows in `portfolio`, `positions`, `orders`, and `trade_history`; the in-memory
engine is a hydrated cache. `GET /api/v1/portfolio`, `/positions`, and `/orders`
hydrate before responding. Promotion reads `trade_history` and the portfolio drawdown.

## Invariants
- PostgreSQL is the source of truth; the engine is never a second durable source.
- A fill, mark, or closure writes one transaction. On failure or rejection, the
  pre-action engine snapshot is restored. An accepted fill with no seeded paper account
  is rejected. A rejected reversal must leave the old position open.
- Fills apply configured commission and adverse slippage.
- Equity marks open positions at the latest price; `total_pnl = equity - initial`.
- Shorts credit proceeds, report 100% notional margin, and subtract the liability from
  equity. Cash and reported PnL reconcile after every fill.
- One open position per symbol (the engine closes an opposite position on reversal).
- `orders.client_order_id` is unique per paper account through a partial unique index.
  Duplicate API requests return 409 and never create a second position.
- Concurrent API/worker/runner writes are still last-writer-wins; idempotency does not add
  row locking or optimistic versions.

## Human check
`GET /api/v1/portfolio`, `/positions`, `/orders`; run `scripts/seed.py` once on a fresh
database to create the paper account/portfolio. `GET` still works without a seed but
returns empty state; writes return 503 rather than persisting in memory.

## Tests
`tests/test_paper_trading.py`, `tests/test_paper_trading_ledger.py`,
`tests/test_paper_trading_worker.py`, `tests/test_execution_agent.py`,
`tests/test_schema.py`.

## Known gaps
Concurrent writers can lose an update; `/execute` trusts the authenticated caller's agent
payload (no signed/expiring token); there is no automated PostgreSQL CI job; the engine
must be constructed with the same fee settings after restart. Stop fills still use the stop
price on a gap, and there are no partial fills or borrow/funding costs. No manual
paper-trade path exists; a future one must be labeled and excluded from promotion.
