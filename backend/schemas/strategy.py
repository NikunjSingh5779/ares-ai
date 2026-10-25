"""Strategy draft schemas.

A strategy draft is configuration, not an order. The API never lets a caller set
``status``, ``live_trading_enabled``, or the promotion counters; those fields stay
owned by the database and the execution/promotion path. The 2% position cap and
every other safety gate remain enforced by the trading path, not by this model.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

StrategyType = Literal[
    "momentum",
    "mean_reversion",
    "trend_following",
    "arbitrage",
    "grid",
    "dca",
    "ml",
    "custom",
]

_INDICATOR_PATTERN = re.compile(r"^[a-z0-9_]{1,30}$")


class StrategyConfig(BaseModel):
    """Indicator selection for a draft strategy."""

    model_config = ConfigDict(extra="forbid")

    indicators: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Indicator identifiers, for example sma, ema, rsi, macd, bb",
    )

    @field_validator("indicators")
    @classmethod
    def _normalize_indicators(cls, values: list[str]) -> list[str]:
        """Trim, lowercase, validate, and deduplicate indicator identifiers."""
        normalized: list[str] = []
        for value in values:
            item = value.strip().lower()
            if not _INDICATOR_PATTERN.fullmatch(item):
                raise ValueError(f"Invalid indicator identifier: {value!r}")
            if item not in normalized:
                normalized.append(item)
        return normalized


class StrategyParameters(BaseModel):
    """Draft risk/entry parameters.

    These are not a safety-limit override. The Risk agent and execution path
    still enforce the configured position cap, risk score, drawdown, and
    exposure limits at trade time.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    position_size_pct: float = Field(
        default=10.0,
        gt=0,
        le=100,
        description="Requested position size percentage; never bypasses the safety cap",
    )
    stop_loss_pct: float = Field(default=5.0, gt=0, le=100)
    take_profit_pct: float = Field(default=15.0, gt=0, le=100)


class StrategyCreate(BaseModel):
    """Create a draft strategy. Status and live fields are server-owned."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    strategy_type: StrategyType
    config: StrategyConfig = Field(default_factory=StrategyConfig)
    parameters: StrategyParameters = Field(default_factory=StrategyParameters)

    @field_validator("name", "description", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class StrategyUpdate(BaseModel):
    """Partially update a draft or paused strategy."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    strategy_type: StrategyType | None = None
    config: StrategyConfig | None = None
    parameters: StrategyParameters | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class StrategyResponse(BaseModel):
    """A persisted strategy with server-owned lifecycle fields."""

    id: UUID
    name: str
    description: str
    strategy_type: StrategyType
    config: StrategyConfig
    parameters: StrategyParameters
    version: int = Field(..., ge=1)
    status: str
    paper_trade_closed_trades: int = Field(default=0, ge=0)
    live_trading_enabled: bool
    created_at: datetime
    updated_at: datetime
