"""Backtest API router — run historical backtests.

Endpoints:
    POST /api/v1/backtest/run — Run a backtest
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.indicators import compute_all_indicators
from agents.quant import _rule_based_quant, VALID_STRATEGIES
from backend.data.ingestor import MarketDataIngestor
from backtesting.engine import BacktestEngine, BacktestInput, Signal

logger = logging.getLogger("ares.api.backtest")
router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])

# Use a default lookback sufficient for technical indicators (e.g., SMA200)
MIN_CANDLES_REQUIRED = 200


class BacktestRequest(BaseModel):
    """Request payload for running a backtest."""

    symbol: str = Field(..., description="Ticker symbol")
    interval: str = Field(default="1d", description="Data interval (e.g. 1d, 1h)")
    initial_capital: float = Field(default=100000.0, description="Starting capital")
    strategy: str = Field(default="momentum", description="Strategy to run")
    days_back: int = Field(default=365 * 2, description="How many days of history to fetch")


@router.post("/run")
async def run_backtest(request: BacktestRequest) -> dict[str, Any]:
    """Run a rule-based backtest on historical data."""
    if request.strategy not in VALID_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid strategy. Must be one of: {', '.join(VALID_STRATEGIES)}",
        )

    # 1. Fetch historical data
    ingestor = MarketDataIngestor()
    from backend.data.models import MarketDataRequest
    try:
        req = MarketDataRequest(
            symbol=request.symbol,
            source="yahoo",
            interval=request.interval,
            limit=request.days_back,
        )
        data_result = await ingestor.ingest(req)
        candles = data_result.candles
    except Exception as e:
        logger.exception("Failed to fetch historical data for backtest")
        raise HTTPException(status_code=500, detail=f"Failed to fetch market data: {e}") from e

    if len(candles) < MIN_CANDLES_REQUIRED:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough data. Got {len(candles)} candles, need at least {MIN_CANDLES_REQUIRED}.",
        )

    # 2. Generate signals iteratively (simulating a live feed)
    signals: list[Signal] = []
    
    # Start simulating from the point where we have enough history for SMA200
    for i in range(MIN_CANDLES_REQUIRED, len(candles)):
        # Provide history up to the current candle
        window = candles[: i + 1]
        current_candle = window[-1]
        
        # Calculate indicators
        inds = compute_all_indicators(window)
        
        # Run the rule-based quant logic (no LLM, fast)
        try:
            quant_out = _rule_based_quant(request.symbol, inds, strategy_hint=request.strategy)
        except Exception as e:
            logger.warning(f"Strategy evaluation failed at index {i}: {e}")
            continue
            
        direction = quant_out.get("direction", "neutral")
        confidence = quant_out.get("confidence", 0.0)
        
        # Only take signals above a basic confidence threshold (e.g. 60%)
        if direction != "neutral" and confidence > 60.0:
            signals.append({
                "direction": direction,
                "timestamp": current_candle.timestamp,
                "strategy_name": quant_out.get("strategy_name", request.strategy),
                "confidence": confidence,
                "stop_loss": quant_out.get("stop_loss"),
                "take_profit": quant_out.get("take_profit"),
            })

    if not signals:
        logger.warning(f"No valid signals generated for {request.symbol} over {len(candles)} candles")
        # Continue anyway, backtest engine handles zero trades gracefully

    # 3. Run backtest engine
    engine_input = BacktestInput(
        symbol=request.symbol,
        candles=candles,
        initial_capital=request.initial_capital,
        signals=signals,
        commission_pct=0.001, # 0.1% typical exchange fee
        slippage_pct=0.001,   # 0.1% slippage
    )
    
    try:
        engine = BacktestEngine()
        result = engine.run(engine_input)
    except Exception as e:
        logger.exception("Backtest engine failed")
        raise HTTPException(status_code=500, detail=f"Backtest engine failed: {e}") from e

    # The result matches the BacktestResult schema, we can return it as dict
    return result.model_dump()
