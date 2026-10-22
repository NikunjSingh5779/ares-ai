"""Market data API schemas.

These mirror the read-only candle shape the dashboard consumes. They are not
agent outputs and carry no trading decision, so they deliberately have no
``rationale`` field.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Candle(BaseModel):
    """One OHLCV candle with a UTC epoch timestamp."""

    model_config = ConfigDict(allow_inf_nan=False)

    time: int = Field(..., description="Candle open time, Unix seconds (UTC)")
    open: float = Field(..., description="Open price")
    high: float = Field(..., description="High price")
    low: float = Field(..., description="Low price")
    close: float = Field(..., description="Close price")
    volume: float = Field(default=0.0, ge=0, description="Trading volume")


class CandlesResponse(BaseModel):
    """Recent candles for one symbol and interval."""

    symbol: str
    interval: str
    source: str
    count: int = Field(..., ge=0)
    candles: list[Candle]
