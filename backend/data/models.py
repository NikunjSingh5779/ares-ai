"""Market data Pydantic models for ARES AI."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Interval:
    """Supported market data intervals."""

    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1mo"

    ALL = [MINUTE_1, MINUTE_5, MINUTE_15, MINUTE_30, HOUR_1, HOUR_4, DAY_1, WEEK_1, MONTH_1]

    @classmethod
    def validate(cls, interval: str) -> str:
        if interval not in cls.ALL:
            raise ValueError(f"Invalid interval '{interval}'. Must be one of: {cls.ALL}")
        return interval


class Source:
    """Supported market data sources."""

    YAHOO = "yahoo"
    COINGECKO = "coingecko"
    BINANCE = "binance"

    ALL = [YAHOO, COINGECKO, BINANCE]

    @classmethod
    def validate(cls, source: str) -> str:
        if source not in cls.ALL:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {cls.ALL}")
        return source


_INTERVAL_ALLOWED = frozenset(Interval.ALL)
_SOURCE_ALLOWED = frozenset(Source.ALL)


class OHLCVData(BaseModel):
    """Single OHLCV candlestick data point."""

    symbol: str = Field(..., description="Ticker symbol (e.g. BTC-USD, AAPL)")
    source: str = Field(..., description="Data source (yahoo, coingecko, binance)")
    interval: str = Field(..., description="Candle interval (1m, 5m, 1h, 1d, etc.)")
    timestamp: datetime = Field(..., description="Candle open time")
    open: float = Field(..., description="Open price")
    high: float = Field(..., description="High price")
    low: float = Field(..., description="Low price")
    close: float = Field(..., description="Close price")
    volume: float = Field(default=0.0, description="Trading volume")
    vwap: float | None = Field(default=None, description="Volume-weighted average price")
    trades_count: int | None = Field(default=None, description="Number of trades (exchange-specific)")

    @field_validator("interval")
    @classmethod
    def _validate_interval(cls, v: str) -> str:
        if v not in _INTERVAL_ALLOWED:
            raise ValueError(f"Invalid interval '{v}'. Must be one of: {sorted(_INTERVAL_ALLOWED)}")
        return v

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        if v not in _SOURCE_ALLOWED:
            raise ValueError(f"Invalid source '{v}'. Must be one of: {sorted(_SOURCE_ALLOWED)}")
        return v

    def model_dump_for_db(self) -> dict[str, Any]:
        """Prepare data for insertion into the market_data table."""
        return {
            "symbol": self.symbol,
            "source": self.source,
            "interval": self.interval,
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "vwap": self.vwap,
            "trades_count": self.trades_count,
        }


class MarketDataRequest(BaseModel):
    """Request to fetch market data."""

    symbol: str = Field(..., description="Ticker symbol (source-specific format)")
    source: str = Field(default="yahoo", description="Data source")
    interval: str = Field(default="1d", description="Candle interval")
    start_date: datetime | None = Field(default=None, description="Start date (inclusive)")
    end_date: datetime | None = Field(default=None, description="End date (inclusive)")
    limit: int = Field(default=100, ge=1, le=1000, description="Max candles to fetch")

    @field_validator("interval")
    @classmethod
    def _validate_interval(cls, v: str) -> str:
        if v not in _INTERVAL_ALLOWED:
            raise ValueError(f"Invalid interval '{v}'. Must be one of: {sorted(_INTERVAL_ALLOWED)}")
        return v

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        if v not in _SOURCE_ALLOWED:
            raise ValueError(f"Invalid source '{v}'. Must be one of: {sorted(_SOURCE_ALLOWED)}")
        return v

    def model_post_init(self, __context: Any) -> None:
        if self.end_date is None:
            object.__setattr__(self, "end_date", datetime.now(UTC))


class MarketDataResult(BaseModel):
    """Result from a market data ingestion request."""

    symbol: str
    source: str
    interval: str
    count: int = 0
    cached: bool = False
    from_cache: int = 0
    from_source: int = 0
    stored: int = 0
    errors: list[str] = Field(default_factory=list)
    start_date: datetime | None = None
    end_date: datetime | None = None
    elapsed_ms: int = 0


class MarketDataQuery(BaseModel):
    """Query parameters for retrieving stored market data."""

    symbol: str
    interval: str = "1d"
    source: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    limit: int = 500
    offset: int = 0
    order: Literal["asc", "desc"] = "desc"


class MarketDataSummary(BaseModel):
    """Summary statistics for a market data query."""

    symbol: str
    source: str
    interval: str
    count: int
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    high: float | None = None
    low: float | None = None
    avg_close: float | None = None
    total_volume: float = 0.0
