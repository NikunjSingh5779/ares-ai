<!-- docs/map/processes/execution.md -->
# Execution and promotion

**Trigger:** approved consensus+risk signal, `POST /api/v1/execute`, `/api/v1/live/*`,
or the runner loop in `scripts/run_live.py`.

## Paper path
`agents/execution.py` → `PaperTradingLedger.execute_signal()` → refresh the
`PaperTradingEngine` cache from `PaperLedgerRepository` → engine fill with configured
commission and adverse slippage → one transaction writing `positions`, entry/exit
orders, reversal `trade_history`, and `portfolio` → `ExecutionOutput`.
`PaperTradingLedger.process_candle()` (used by `paper_trading/worker.py` and the
runner) checks SL/TP, marks the remaining position, and persists the result. A failed
write restores the cache snapshot; an accepted fill with no seeded account is rejected.
PnL is equity-based, including open marks and fees.

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
Order idempotency; `get_open_orders()` returns `[]`; no balance reconciliation.
Concurrent API/worker/runner paper writes are last-writer-wins (no row lock or
optimistic version). `/execute` bypasses consensus/risk and role checks; promotion can
therefore be distorted by a manual paper trade. A Redis outage blocks orders and
requires a human re-arm (intentional); the latch is process-local, so a runner that
latched also needs a restart until a shared arm epoch exists.
