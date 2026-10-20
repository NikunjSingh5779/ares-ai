<!-- docs/map/processes/execution.md -->
# Execution and promotion

**Trigger:** approved consensus+risk signal, `POST /api/v1/execute`, `/api/v1/live/*`,
or the runner loop in `scripts/run_live.py`.

## Paper path
`agents/execution.py` → `PaperTradingEngine.execute_signal()` (configured commission
and adverse slippage, actual fill/quantity) → `positions` + reversal `trade_history`
rows → `ExecutionOutput`. `paper_trading/worker.py` marks each candle, closes SL/TP,
writes `trade_history`, and mirrors the portfolio projection. PnL is equity-based,
including open marks and fees.

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
`set_mode(auto)`. Paper accounting now includes fees, adverse slippage, and intra-trade
marks; the worker inserts SL/TP closures so normal exits count. The remaining durability
gap is that the engine is in memory and the DB is a projection.

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
Order idempotency; `get_open_orders()` returns `[]`; no balance reconciliation.
The paper engine is in-memory and the DB portfolio is only synced when the worker
closes a trade; `positions` has no side column. A Redis outage blocks orders and
requires a human re-arm (intentional); the latch is process-local, so a runner that
latched also needs a restart until a shared arm epoch exists.
