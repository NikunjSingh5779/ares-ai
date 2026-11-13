<!-- paper_trading/CONTEXT.md -->
# paper_trading/ — contract

**Purpose:** simulated fills, portfolio accounting, and the durable paper ledger. No
LLM, no exchange.

## Files
- `engine.py` — `PaperTradingEngine`, `PaperPosition`, `ClosedTrade`,
  `PortfolioSummary`; snapshot/restore/hydration APIs.
- `repository.py` — `PaperLedgerRepository`; the only SQL reader/writer for the
  paper account, portfolio, open positions, orders, and closed-trade history. Also owns
  `writer_lock()`, the transaction-scoped advisory lock that serializes writers.
- `ledger.py` — `PaperTradingLedger`; takes the in-process cache lock and the repository
  writer lock, refreshes the cache, mutates the engine, writes one transaction, and
  restores the cache on failure.
- `worker.py` — polling loop that checks stop-loss/take-profit on incoming candles
  through the ledger.

## Inputs
- Approved signal: symbol, side, quantity, price.
- For API `/execute`, a typed approval payload plus `client_order_id`; the router derives
  quantity, price, and stop-loss before calling the ledger.
- Candles for marks and SL/TP checks.
- `paper_trading_initial_capital`, `paper_trading_commission_pct`,
  `paper_trading_slippage_pct`, and optional `paper_trading_slippage_by_symbol`
  overrides (JSON object, e.g. `{"BTC-USD": 0.002}`) from settings. The application
  constructs its engine with 10 bps each by default; direct engine construction
  defaults to zero for unit tests. Fee/slippage settings are configuration, not
  persisted state, so every process that hydrates the ledger must construct its
  engine with the same settings. A symbol missing from the override map uses the
  global slippage rate.
- Annualized carry: `paper_trading_borrow_rate_pct` (default `0.10` = 10%/year,
  charged on short notional), `paper_trading_funding_rate_pct` (default `0.0`,
  charged on long notional), and optional `paper_trading_borrow_rate_by_symbol` /
  `paper_trading_funding_rate_by_symbol` JSON overrides. Rates are non-negative
  decimals; there are no funding credits. A symbol missing from a map falls back
  to the global rate. Carry settings are configuration, not persisted state.
- Liquidity: `paper_trading_max_volume_participation_pct` (default `0.10`) caps an
  IOC market fill at that fraction of the candle volume. `0` disables the cap; the
  application wires the non-zero default while direct engine construction stays at
  `0.0` for unit tests. A missing or non-positive candle volume means "unknown", so
  no cap is applied rather than rejecting every fill. Volume sources: API `/execute`
  reads `current_volume` from the approved Market Analyst indicators (hash-bound to
  the approval token); the execution agent, worker, and runner pass the latest
  candle's volume. Like fees, the cap is configuration, not persisted state.
- `paper_trading_writer_lock_timeout_seconds` (default 10 s) bounds how long a write
  waits for the cross-process advisory lock.

## Process
1. `PaperTradingLedger.execute_signal` takes the cache lock and the repository writer
   lock, refreshes from PostgreSQL, rejects an already-used
   `client_order_id`, snapshots the engine, closes an opposite position if present,
   applies adverse slippage, sizes against cash (long) or equity with 100% short
   margin, caps the fill at the participation fraction of candle volume when a cap is
   configured and volume is known, records the position (with
   `requested_quantity`/`entry_order_status` metadata), and debits/credits cash
   including entry commission on the filled quantity. The unfilled remainder is
   cancelled (IOC): the result reports `requested_quantity`, `filled_quantity`,
   `unfilled_quantity`, `order_status` (`filled`/`partially_filled`/`rejected`),
   `liquidity_capped`, and `unfilled_reason`. It persists the open position, entry
   order with its client ID and filled size, any reversal close/history, and
   portfolio in one transaction. Exit orders carry no client ID.
2. `PaperTradingLedger.process_candle` takes the same two locks, refreshes, checks SL/TP
   first (stop first when a candle spans both levels), accrues carry to the candle
   timestamp, marks any remaining open position, and persists the closure and/or mark.
   The worker and runner pass the candle open: when it is already beyond a stop, the
   stop fills at the open (gap-through) and then takes the usual adverse slippage;
   take-profit still fills at its configured level. Callers that pass no open keep the
   stop-level fill. Repeated calls with the same timestamp do not double-charge carry.
   A triggered exit is also volume-limited: it closes at most the participation
   fraction of candle volume and leaves the remainder open (with its stop and accrual
   clock) for the next candle; unknown volume closes the full position.
3. `mark_to_market` accrues carry for every open position, updates the latest price, and
   appends equity on every bar. `close_position` accrues the final partial period,
   applies exit slippage and commission, settles carry into cash and PnL, and appends
   equity. With `quantity=`, it closes only that many units: entry commission and
   accrued carry are allocated to the closed lot proportionally, and the remaining
   position keeps its stop/take-profit, entry price, and accrual clock (short margin
   becomes `remaining_qty × entry_price`). Each partial close appends one `ClosedTrade`
   lot.
4. `get_summary` returns cash, equity, margin used, all-in PnL, return %, win rate,
   drawdown, and total carry (open plus closed) from the persisted state.

## Outputs
Durable rows in `portfolio`, `positions`, `orders`, and `trade_history`; the in-memory
engine is a hydrated cache. `GET /api/v1/portfolio`, `/positions`, and `/orders`
hydrate before responding. Promotion reads `trade_history` and the portfolio drawdown.

## Invariants
- PostgreSQL is the source of truth; the engine is never a second durable source.
- A fill, mark, or closure writes one transaction. On failure or rejection, the
  pre-action engine snapshot is restored. An accepted fill with no seeded paper account
  is rejected. A rejected reversal must leave the old position open.
- Fills apply configured commission and adverse slippage; a per-symbol slippage
  override replaces the global rate for that symbol and every other symbol falls back
  to the global rate. Gap-through stops fill at the candle open, not the stop level.
- Equity marks open positions at the latest price; `total_pnl = equity - initial`.
  Accrued carry is a liability: it is subtracted from equity while the position is open
  and settled into cash and realized PnL when the position closes.
- Shorts credit proceeds, report 100% notional margin, and subtract the liability from
  equity. Cash and reported PnL reconcile after every fill.
- Carry accrues on entry notional at the annual rate for elapsed time since
  `last_accrual_at` (365-day year). It is a cost only: borrow applies to shorts, funding
  to longs, and neither is ever credited. A timestamp at or before the stored clock is
  ignored; a zero rate still advances the clock.
- One open position per symbol (the engine closes an opposite position on reversal).
- Market orders are immediate-or-cancel: a fill above the volume-participation cap
  persists as `partially_filled` and the unfilled remainder is cancelled. A partial
  exit (closed trade whose position is still open) records trade history and an exit
  order tagged `partial: true` but does not close the position row; the remaining
  quantity/commission/margin/carry/clock are upserted from engine state. Hydration
  reports `requested_quantity = quantity` and status `filled` because the requested
  size is not a persisted column. One `trade_history` row is written per realized lot,
  so trade counts and win rate count lots, not positions.
- `orders.client_order_id` is unique per paper account through a partial unique index.
  Duplicate API requests return 409 and never create a second position. Retrying a
  partially filled order requires a new `client_order_id` (IOC is terminal).
- API, worker, and runner writers serialize on `pg_try_advisory_xact_lock` for the whole
  hydrate → mutate → persist cycle; the lock is transaction-scoped so it cannot leak onto
  a pooled connection. A writer that times out raises `PaperLedgerBusyError` and mutates
  nothing.
- The shared in-process engine cache is guarded by an `asyncio.Lock`, so a read cannot
  re-hydrate mid-write.

## Human check
`GET /api/v1/portfolio`, `/positions`, `/orders`; run `scripts/seed.py` once on a fresh
database to create the paper account/portfolio. `GET` still works without a seed but
returns empty state; writes return 503 rather than persisting in memory.

## Tests
`tests/test_paper_trading.py`, `tests/test_paper_trading_ledger.py`,
`tests/test_paper_trading_worker.py`, `tests/test_execution_agent.py`,
`tests/test_schema.py`, `tests/test_postgres_integration.py`.

## Known gaps
The advisory lock is database-wide rather than per account (fine for one seeded paper
account). The `postgres-integration` CI job covers the ledger; the engine must be
constructed with the same fee/slippage/carry/participation settings after restart,
including the per-symbol override maps. Carry is charged on entry notional only (not
mark-to-market notional) and has no funding credits. Liquidity is a hard participation
cap on candle volume, not a price-impact model, and volume is whatever the configured
source reports (CoinGecko reports none, which disables the cap). A partial entry is not
retried: the remainder is cancelled and requires a new approved order. No manual
paper-trade path exists; a future one must be labeled and excluded from promotion.
