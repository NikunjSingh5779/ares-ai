"""Backtesting package — historical simulation and performance metrics."""

from backtesting.engine import (
    BacktestEngine,
    BacktestInput,
    BacktestMetrics,
    BacktestResult,
    SimulatedTrade,
)

__all__ = [
    "BacktestEngine",
    "BacktestInput",
    "BacktestMetrics",
    "BacktestResult",
    "SimulatedTrade",
]
