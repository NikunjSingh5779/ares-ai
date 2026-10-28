<!-- docs/map/processes/execution.md -->
# Execution and promotion

**Trigger:** approved consensus+risk signal, `POST /api/v1/execute`, `/api/v1/live/*`,
or the runner loop in `scripts/run_live.py`.

## Paper path
Two callers share one ledger:

- **Pipeline:** `agents/execution.py` → `PaperTradingLedger.execute_signal()`. The
  graph reaches this node only when `AgentState.execute_trades` is true (the default).
- **API:** `POST /api/v1/execute` → verify the signed `approval_token` (signature,
  expiry, type, audience, issuer, symbol, side, payload digest) → validate typed Market
  Analyst, Quant, and Risk approvals → re-run `ConsensusEngine.evaluate` → derive price
  from the approved `current_price` and quantity from `risk.max_position_size` → enforce
  the 2% equity cap → `PaperTradingLedger.execute_signal()`.

`POST /signal` is the only issuer of approval tokens. With `execute=false` it runs the
graph through risk, skips this node, and returns the typed approval plus a short-lived
JWT signed with `JWT_SECRET_KEY` (claims and limits: ADR-025). With the default
`execute=true` it executes immediately and returns no token. `/execute` rejects an
invalid or expired token with **401** and a token that does not match the submitted
symbol, side, or payload with **422**; neither reaches the ledger.

The ledger refreshes the `PaperTradingEngine` cache from `PaperLedgerRepository`, applies
configured commission and adverse slippage, then writes `positions`, entry/exit orders,
reversal `trade_history`, and `portfolio` in one transaction. Every write holds an
in-process cache lock and a PostgreSQL transaction-scoped advisory lock
(`pg_try_advisory_xact_lock`) across hydrate → mutate → persist, so API, worker, and runner
serialize instead of overwriting each other. A writer that cannot get the lock within
`PAPER_TRADING_WRITER_LOCK_TIMEOUT_SECONDS` fails with **503** and no mutation.
`client_order_id` is
required on the API path and checked before mutation; a partial unique index on
`orders(account_id, client_order_id)` protects concurrent retries. A duplicate returns
**409** and never creates a second position. A failed or conflicting write restores the
cache snapshot; an accepted fill with no seeded account is rejected.
`PaperTradingLedger.process_candle()` (used by `paper_trading/worker.py` and the
runner) checks SL/TP, marks the remaining position, and persists the result. PnL is
equity-based, including open marks and fees. There is no manual `/execute` bypass;
manual trades would need a separately designed label that excludes them from promotion.

## Live path
`ExecutionAgent` → `LiveTradingEngine.execute_signal()` →
1. `settings.live_trading_enabled` (paper-only backstop)
2. `KillSwitch.check()` (shared Redis; fails closed and latches)
3. `ModeManager` (human_approval / semi / auto)
4. `PromotionGate` (min paper trades and days)
5. exchange connected
6. `exchange.create_order`
7. `OrderAuditor` records the full rationale chain

`ExecutionAgent` reaches this branch only when live is enabled, the engine is
running and connected, mode is `AUTO`, and the promotion gate passed. The only
production `exchange.create_order` call site is `live_trading/engine.py`.

## Promotion
`PromotionGate` queries `trade_history` for closed trades and distinct days, and
`portfolio.max_drawdown_pct` for the drawdown check. Passing it is a prerequisite for
`set_mode(auto)`. Paper accounting includes fees, adverse slippage, and intra-trade
marks; the ledger writes SL/TP closures so normal exits count and survive restart.

## Human check
- `/api/v1/live/status` shows mode, kill-switch state, paper record, engine state.
- `/api/v1/live/audit` lists orders with the approving agents and risk checks.
- `promotion` returns a machine-checkable reason when blocked.

## Change impact
- New exchange → `live_trading/exchange/<name>.py` + `create_exchange` + settings + tests.
- Change a gate → `live_trading/safety.py`, `engine.py`, gate tests, this card.
- Change promotion thresholds → `configs/settings.py`, `.env.example`, gate tests.

## Tests
`tests/test_live_trading/*` (engine, safety, routes, audit, exchanges),
`tests/test_agents/test_execution_live_routing.py`, `tests/test_paper_trading.py`.

## Known gaps
`get_open_orders()` returns `[]`; no balance reconciliation. Paper writers serialize on a
database-wide advisory lock (per account would be finer). `/execute` requires a signed,
expiring approval token from `/signal` with `execute=false`, so an authenticated caller
cannot submit a fabricated agent payload; the token is not single-use, and
`client_order_id` remains the duplicate-order guard. `ExecutionAgent` keeps a legacy
in-memory/direct-SQL fallback when constructed
without a `ledger`; production paths (`backend/routers/analysis.py`, `scripts/run_live.py`)
always pass the ledger, and the fallback bypasses the writer lock — do not use it for paper
writes. Trading and live controls require `operator` or higher through
`require_trading_access` / `require_live_control`; `viewer` is read-only and the role check
does not query PostgreSQL. A Redis outage blocks orders and requires a human re-arm
(intentional). `arm()` publishes an `arm:` epoch token, so one re-arm clears every process
that had observed the shared state; a missing/flushed token, a republished baseline, or
recovery alone never clears a latch. A process that latched before its first successful
read needs one further arm.
