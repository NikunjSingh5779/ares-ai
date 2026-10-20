<!-- backtesting/CONTEXT.md -->
# backtesting/ — contract

**Purpose:** deterministic historical simulation and performance metrics.

## Files
- `engine.py` — candle replay, signal mapping, fill simulation, metric computation.

## Inputs
- OHLCV candles (ascending time).
- `Signal` list (symbol, side, entry/exit, optional price).
- `BacktestConfig`: initial capital, commission, slippage, position size.

## Process
1. Map signals to candle indices.
2. Enter at the next candle’s open unless a fixed price is given (no look-ahead).
3. Apply commission and slippage to entry/exit.
4. Replay SL/TP and exits; build the equity curve and trade list.
5. Compute Sharpe, Sortino, win rate, profit factor, max drawdown, expectancy,
   recovery factor.

## Outputs
`BacktestResult` (metrics + trades + equity curve); `backend/routers/backtest.py` returns it
and persists to the `backtests` table.

## Invariants
- No future data in a decision.
- Fees and slippage are explicit and configurable.
- Same input → same output (no randomness, no LLM).
- Metrics match the `backtests` schema.

## Human check
`POST /api/v1/backtest/run`, then inspect trades and the equity curve in `/backtests`.

## Tests
`tests/test_backtesting.py`, `tests/test_backend_backtest.py`.

## Change impact
A new metric or config field → engine, result model, router schema, frontend type, tests.
