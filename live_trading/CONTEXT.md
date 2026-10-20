<!-- live_trading/CONTEXT.md -->
# live_trading/ — contract

**Purpose:** place real orders behind deterministic safety gates and keep an audit trail.

## Files
- `engine.py` — `LiveTradingEngine.execute_signal`, drawdown evaluation, order queries.
- `safety.py` — `KillSwitch`, `ModeManager`, `PromotionGate`, `TradingMode`, `SafetyCheckResult`.
- `audit.py` — `OrderAuditor` (in-memory entries, exported via `/live/audit`).
- `exceptions.py` — `KillSwitchTrippedError`, `ModeError`, `PromotionGateError`, `ExchangeConnectionError`.
- `exchange/` — `base.py` + binance, bybit, coinbase, kraken, zerodha, ibkr.

## Gate order (must not be reordered)
1. Kill switch active → block.
2. Mode = human_approval → require approval.
3. Promotion gate → block without a sufficient paper record.
4. Exchange connected → block if not.
5. Risk approval (upstream) → block otherwise.
6. Place order → audit.

## Inputs
Approved signal, settings (`live_trading_enabled`, `live_max_drawdown_pct`,
`minimum_paper_trades`, `minimum_paper_days`), exchange credentials, Redis for shared
state.

## Outputs
Order result, `live_trades` row, audit entry, `LIVE_ORDERS_TOTAL` / kill-switch gauge.

## Invariants
- `execute_signal` is the **only** path to `create_order`.
- Live trading is opt-in: `LIVE_TRADING_ENABLED=false` blocks `start()` and
  `execute_signal()` at the engine, not just the API.
- Kill switch uses shared Redis, fails closed on any Redis error, latches, and requires
  a human `arm()` after recovery.
- Default mode is `human_approval`; auto is opt-in per strategy.
- Every order logs the approving agents and checks.

## Human check
`/api/v1/live/status`, `/audit`, `/paper_record`; trip and re-arm the switch in staging.
With Redis stopped, status must report `storage_healthy=false` and orders must block.

## Tests
`tests/test_live_trading/*`, `tests/test_agents/test_execution_live_routing.py`.

## Known gaps
No idempotency or reconciliation; `get_open_orders()` returns `[]`. Paper accounting
now includes fees, adverse slippage, and intra-trade marks, and the worker writes SL/TP
closures to `trade_history`; the remaining optimism is durability, because the engine
is in memory and the portfolio row is a projection. The fail-closed latch is
process-local: after a Redis recovery an API `arm()` clears the API process, but a
runner that also latched must be restarted until a shared arm epoch is implemented.
