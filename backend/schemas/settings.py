"""Settings API schemas.

Only dashboard preferences are mutable. Trading safety limits are computed from
the same constants the execution path enforces, so the UI cannot drift from the
backend or raise a limit through this API.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DashboardPreferences(BaseModel):
    """Preferences the dashboard actually consumes.

    These affect presentation and polling only. They are never used to size a
    trade, approve a signal, or change a safety gate.
    """

    model_config = ConfigDict(extra="forbid")

    default_symbol: str = Field(
        default="BTC-USD",
        min_length=1,
        max_length=20,
        pattern=r"^[A-Z0-9^.=:/-]+$",
        description="Initial symbol for the dashboard quick analysis and markets chart",
    )
    live_refresh_seconds: int = Field(
        default=5,
        ge=5,
        le=30,
        description="Polling interval for live status, in seconds (5-30)",
    )

    @field_validator("default_symbol", mode="before")
    @classmethod
    def _normalize_symbol(cls, value: object) -> object:
        """Trim and uppercase ticker input before the pattern is checked."""
        return value.strip().upper() if isinstance(value, str) else value


class SafetyLimits(BaseModel):
    """Read-only limits enforced by the trading path."""

    max_position_size_pct: float = Field(..., gt=0)
    max_risk_score: float = Field(..., ge=0, le=100)
    min_consensus_confidence_pct: float = Field(..., ge=0, le=100)
    live_max_drawdown_pct: float = Field(..., gt=0)
    minimum_paper_trades: int = Field(..., ge=0)
    minimum_paper_days: int = Field(..., ge=0)
    live_trading_enabled: bool


class SettingsResponse(BaseModel):
    """Effective runtime safety limits plus the persisted dashboard preferences."""

    safety: SafetyLimits
    preferences: DashboardPreferences
