"""Safety gates for live trading.

Enforced in this order (evaluated by the engine before any trade)::

    1. KillSwitch active?            → BLOCK
    2. Mode = human_approval?        → require explicit approval
    3. PromotionGate passed?         → BLOCK if insufficient paper record
    4. Exchange connected?           → BLOCK if disconnected
    5. RiskAgent approved?           → BLOCK if rejected (handled upstream)

All checks are deterministic Python — no LLM calls.
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Any


class TradingMode(str, Enum):
    """Live trading mode."""

    HUMAN_APPROVAL = "human_approval"
    SEMI = "semi"
    AUTO = "auto"


class SafetyCheckResult:
    """Result of a single safety gate check."""

    def __init__(self, passed: bool, reason: str = "") -> None:
        self.passed = passed
        self.reason = reason

    def __bool__(self) -> bool:
        return self.passed

    def __repr__(self) -> str:
        return f"SafetyCheckResult(passed={self.passed}, reason={self.reason!r})"


class KillSwitch:
    """Global kill switch — halts all live order placement immediately.

    Two activation modes:

    - **Manual**: triggered by operator via ``.activate()``.
    - **Automatic**: triggered when a drawdown or circuit-breaker
      threshold is breached via ``.auto_trigger()``.

    Once active, a human must call ``.arm()`` to re-enable trading.
    """

    def __init__(self, max_drawdown_pct: float = 15.0) -> None:
        self._active = False
        self._triggered_by: str | None = None
        self._triggered_at: datetime.datetime | None = None
        self._auto_drawdown_pct = max_drawdown_pct

    # ── State ──────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """``True`` if the kill switch has been tripped."""
        return self._active

    @property
    def triggered_by(self) -> str | None:
        """Who or what triggered the kill switch."""
        return self._triggered_by

    @property
    def triggered_at(self) -> datetime.datetime | None:
        """When the kill switch was triggered."""
        return self._triggered_at

    @property
    def max_drawdown_pct(self) -> float:
        """Maximum allowed drawdown before auto-trigger."""
        return self._auto_drawdown_pct

    # ── Control ────────────────────────────────────────────────────

    def activate(self, reason: str = "manual") -> None:
        """Manually activate the kill switch."""
        self._active = True
        self._triggered_by = reason
        self._triggered_at = datetime.datetime.now(datetime.timezone.utc)

    def auto_trigger(self, drawdown_pct: float) -> bool:
        """Automatically trigger if *drawdown_pct* exceeds the threshold.

        Returns ``True`` if the switch was tripped, ``False`` otherwise.
        """
        if drawdown_pct >= self._auto_drawdown_pct and not self._active:
            self._active = True
            self._triggered_by = f"auto:drawdown={drawdown_pct:.1f}%"
            self._triggered_at = datetime.datetime.now(datetime.timezone.utc)
            return True
        return False

    def arm(self) -> None:
        """Re-arm the kill switch (human confirmation required)."""
        self._active = False
        self._triggered_by = None
        self._triggered_at = None

    # ── Pre-trade check ────────────────────────────────────────────

    def check(self) -> SafetyCheckResult:
        """Safe-guard check: is the kill switch active?"""
        if self._active:
            return SafetyCheckResult(
                passed=False,
                reason=f"Kill switch active — triggered by: {self._triggered_by}",
            )
        return SafetyCheckResult(passed=True)


class ModeManager:
    """Manages the live trading mode.

    The system starts in ``HUMAN_APPROVAL`` by default — every live order
    requires explicit human approval. Autonomous mode must be explicitly
    enabled.

    Modes::

        human_approval   — every order requires human approval
        semi             — human approval or automated (per-strategy config)
        auto             — fully autonomous (orders placed without human input)
    """

    def __init__(self, initial_mode: TradingMode = TradingMode.HUMAN_APPROVAL) -> None:
        self._mode = initial_mode

    @property
    def mode(self) -> TradingMode:
        return self._mode

    def set_mode(self, new_mode: TradingMode) -> None:
        """Change the trading mode."""
        self._mode = new_mode

    def requires_approval(self) -> bool:
        """Does the current mode require human approval before each order?"""
        return self._mode == TradingMode.HUMAN_APPROVAL

    def check(self) -> SafetyCheckResult:
        """Safe-guard check: does the current mode require approval?

        Returns ``passed=True`` for all modes — this check does not block
        the trade pipeline; it signals whether the engine should request
        human approval before placing the order.
        """
        if self._mode == TradingMode.HUMAN_APPROVAL:
            return SafetyCheckResult(
                passed=True,
                reason="Mode is human_approval — human confirmation required before order",
            )
        return SafetyCheckResult(passed=True, reason=f"Mode is {self._mode.value}")


class PromotionGate:
    """Prevents a strategy from going live without a sufficient paper record.

    Minimum requirements (configurable)::

        min_paper_trades = 50   (default)
        min_paper_days   = 30   (default)

    The gate passes only when **both** thresholds are met or exceeded.
    """

    def __init__(
        self,
        min_paper_trades: int = 50,
        min_paper_days: int = 30,
    ) -> None:
        self.min_paper_trades = min_paper_trades
        self.min_paper_days = min_paper_days

    def passed(self, paper_trades_count: int, paper_days_count: int) -> bool:
        """Check if the paper record satisfies the promotion requirements."""
        return (
            paper_trades_count >= self.min_paper_trades
            and paper_days_count >= self.min_paper_days
        )

    def check(self, paper_trades_count: int, paper_days_count: int) -> SafetyCheckResult:
        """Safe-guard check: does the paper record meet promotion criteria?"""
        if not self.passed(paper_trades_count, paper_days_count):
            return SafetyCheckResult(
                passed=False,
                reason=(
                    f"Paper record insufficient: "
                    f"{paper_trades_count}/{self.min_paper_trades} trades, "
                    f"{paper_days_count}/{self.min_paper_days} days"
                ),
            )
        return SafetyCheckResult(passed=True)

    def progress(self, paper_trades_count: int, paper_days_count: int) -> dict[str, Any]:
        """Return progress as a dict for the frontend."""
        return {
            "trades": {"current": paper_trades_count, "required": self.min_paper_trades},
            "days": {"current": paper_days_count, "required": self.min_paper_days},
            "passed": self.passed(paper_trades_count, paper_days_count),
        }
