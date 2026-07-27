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
from enum import StrEnum
from typing import Any, Literal

import redis

from backend.core.metrics import set_kill_switch_active


class TradingMode(StrEnum):
    """Live trading mode."""

    HUMAN_APPROVAL = "human_approval"
    SEMI = "semi"
    AUTO = "auto"


SafetyCode = Literal["kill_switch", "mode", "promotion_gate", "exchange", "ok"]
"""Machine-checkable identifier for which gate produced a result.

Callers (e.g. ``LiveTradingEngine._raise_if_blocked``) MUST branch on
``SafetyCheckResult.code`` rather than parsing ``reason`` text. ``reason``
is a human-readable audit string and may be reworded at any time without
changing gate behavior; ``code`` is the stable contract.
"""


class SafetyCheckResult:
    """Result of a single safety gate check.

    ``code`` identifies which gate produced this result and is stable
    across wording changes to ``reason`` — always branch on ``code``,
    never on substrings of ``reason``.
    """

    def __init__(self, passed: bool, reason: str = "", code: SafetyCode = "ok") -> None:
        self.passed = passed
        self.reason = reason
        self.code = code

    def __bool__(self) -> bool:
        return self.passed

    def __repr__(self) -> str:
        return f"SafetyCheckResult(passed={self.passed}, code={self.code!r}, reason={self.reason!r})"


class KillSwitch:
    """Global kill switch — halts all live order placement immediately.

    Two activation modes:

    - **Manual**: triggered by operator via ``.activate()``.
    - **Automatic**: triggered when a drawdown or circuit-breaker
      threshold is breached via ``.auto_trigger()``.

    Once active, a human must call ``.arm()`` to re-enable trading.

    Uses **in-memory state by default** for testability. Pass a ``redis.Redis``
    client for shared atomic state across concurrent agents in production.
    """

    def __init__(self, max_drawdown_pct: float = 15.0, redis_client: redis.Redis | None = None) -> None:
        self._auto_drawdown_pct = max_drawdown_pct
        self._redis_client = redis_client
        # In-memory fallback when Redis is not configured
        self._mem: dict[str, str] = {}

    # ── Storage abstraction ────────────────────────────────────────

    def _get(self, key: str) -> str | None:
        if self._redis_client is not None:
            try:
                val = self._redis_client.get(key)
                return val.decode() if isinstance(val, bytes) else val
            except redis.ConnectionError:
                return None
        return self._mem.get(key)

    def _set(self, key: str, value: str, nx: bool = False) -> bool:
        if self._redis_client is not None:
            try:
                return bool(self._redis_client.set(key, value, nx=nx))
            except redis.ConnectionError:
                return False
        if nx and key in self._mem:
            return False
        self._mem[key] = value
        return True

    def _delete(self, *keys: str) -> None:
        if self._redis_client is not None:
            try:
                self._redis_client.delete(*keys)
            except redis.ConnectionError:
                pass
        else:
            for k in keys:
                self._mem.pop(k, None)

    # ── State ──────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """``True`` if the kill switch has been tripped."""
        return self._get("ares:kill_switch:active") == "1"

    @property
    def triggered_by(self) -> str | None:
        """Who or what triggered the kill switch."""
        return self._get("ares:kill_switch:reason")

    @property
    def triggered_at(self) -> datetime.datetime | None:
        """When the kill switch was triggered."""
        ts = self._get("ares:kill_switch:timestamp")
        if ts:
            if isinstance(ts, bytes):
                return datetime.datetime.fromisoformat(ts.decode("utf-8"))
            return datetime.datetime.fromisoformat(ts)
        return None

    @property
    def max_drawdown_pct(self) -> float:
        """Maximum allowed drawdown before auto-trigger."""
        return self._auto_drawdown_pct

    # ── Control ────────────────────────────────────────────────────

    def activate(self, reason: str = "manual") -> None:
        """Manually activate the kill switch."""
        if self._set("ares:kill_switch:active", "1", nx=True):
            self._set("ares:kill_switch:reason", reason)
            self._set("ares:kill_switch:timestamp", datetime.datetime.now(datetime.UTC).isoformat())
            set_kill_switch_active(True)

    def auto_trigger(self, drawdown_pct: float) -> bool:
        """Automatically trigger if *drawdown_pct* exceeds the threshold.

        Returns ``True`` if the switch was tripped, ``False`` otherwise.
        """
        if drawdown_pct >= self._auto_drawdown_pct:
            reason = f"auto:drawdown={drawdown_pct:.1f}%"
            # Atomic set NX prevents race conditions
            if self._set("ares:kill_switch:active", "1", nx=True):
                self._set("ares:kill_switch:reason", reason)
                self._set("ares:kill_switch:timestamp", datetime.datetime.now(datetime.UTC).isoformat())
                set_kill_switch_active(True)
                return True
        return False

    def arm(self) -> None:
        """Re-arm the kill switch (human confirmation required)."""
        self._delete("ares:kill_switch:active", "ares:kill_switch:reason", "ares:kill_switch:timestamp")
        set_kill_switch_active(False)

    # ── Pre-trade check ────────────────────────────────────────────

    def check(self) -> SafetyCheckResult:
        """Safe-guard check: is the kill switch active?"""
        if self.is_active:
            reason = self.triggered_by or "unknown"
            return SafetyCheckResult(
                passed=False,
                reason=f"Kill switch active — triggered by: {reason}",
                code="kill_switch",
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

        Returns ``passed=False`` for HUMAN_APPROVAL mode to block order
        placement until explicit approval is provided. Other modes pass.
        """
        if self._mode == TradingMode.HUMAN_APPROVAL:
            return SafetyCheckResult(
                passed=False,
                reason="Mode is human_approval — human confirmation required before order",
                code="mode",
            )
        return SafetyCheckResult(passed=True, reason=f"Mode is {self._mode.value}", code="mode")


class PromotionGate:
    """Prevents a strategy from going live without a sufficient *and healthy* paper record.

    Minimum requirements (configurable)::

        min_paper_trades      = 50     (default)
        min_paper_days        = 30     (default)
        max_paper_drawdown_pct = 20.0  (default) — paper max drawdown must not exceed this
        require_non_negative_pnl = True (default) — paper record must not be net-losing

    The gate passes only when **all** thresholds are met. Track record (trade
    count / days) alone is not sufficient — a strategy that racked up enough
    trades and days while bleeding money or blowing through drawdown limits
    must still be blocked. This matches the "minimum paper-trading track
    record ... meeting the Risk Agent's thresholds" requirement in AGENTS.md;
    trade-count/day thresholds alone do not evaluate whether that record was
    any good.

    ``total_pnl`` and ``max_drawdown_pct`` are optional so existing callers
    that only track counts keep working — but when they are omitted, the
    risk-quality checks are skipped, which is a degraded (not a safer) mode.
    Callers wired to the database (see ``LiveTradingEngine``) should always
    supply them.
    """

    def __init__(
        self,
        min_paper_trades: int = 50,
        min_paper_days: int = 30,
        max_paper_drawdown_pct: float = 20.0,
        require_non_negative_pnl: bool = True,
    ) -> None:
        self.min_paper_trades = min_paper_trades
        self.min_paper_days = min_paper_days
        self.max_paper_drawdown_pct = max_paper_drawdown_pct
        self.require_non_negative_pnl = require_non_negative_pnl

    def passed(
        self,
        paper_trades_count: int,
        paper_days_count: int,
        *,
        total_pnl: float | None = None,
        max_drawdown_pct: float | None = None,
    ) -> bool:
        """Check if the paper record satisfies all promotion requirements."""
        return self._failure_reason(paper_trades_count, paper_days_count, total_pnl, max_drawdown_pct) is None

    def _failure_reason(
        self,
        paper_trades_count: int,
        paper_days_count: int,
        total_pnl: float | None,
        max_drawdown_pct: float | None,
    ) -> str | None:
        """Return the first failing reason, or ``None`` if all criteria pass."""
        if paper_trades_count < self.min_paper_trades or paper_days_count < self.min_paper_days:
            return (
                f"Paper record insufficient: "
                f"{paper_trades_count}/{self.min_paper_trades} trades, "
                f"{paper_days_count}/{self.min_paper_days} days"
            )
        if max_drawdown_pct is not None and max_drawdown_pct > self.max_paper_drawdown_pct:
            return (
                f"Paper record fails risk threshold: max drawdown "
                f"{max_drawdown_pct:.1f}% exceeds allowed {self.max_paper_drawdown_pct:.1f}%"
            )
        if self.require_non_negative_pnl and total_pnl is not None and total_pnl < 0:
            return f"Paper record fails risk threshold: net paper PnL is negative (${total_pnl:,.2f})"
        return None

    def check(
        self,
        paper_trades_count: int,
        paper_days_count: int,
        *,
        total_pnl: float | None = None,
        max_drawdown_pct: float | None = None,
    ) -> SafetyCheckResult:
        """Safe-guard check: does the paper record meet all promotion criteria?"""
        failure = self._failure_reason(paper_trades_count, paper_days_count, total_pnl, max_drawdown_pct)
        if failure is not None:
            return SafetyCheckResult(passed=False, reason=failure, code="promotion_gate")
        return SafetyCheckResult(passed=True, code="promotion_gate")

    def progress(
        self,
        paper_trades_count: int,
        paper_days_count: int,
        *,
        total_pnl: float | None = None,
        max_drawdown_pct: float | None = None,
    ) -> dict[str, Any]:
        """Return progress as a dict for the frontend."""
        return {
            "trades": {"current": paper_trades_count, "required": self.min_paper_trades},
            "days": {"current": paper_days_count, "required": self.min_paper_days},
            "risk": {
                "total_pnl": total_pnl,
                "max_drawdown_pct": max_drawdown_pct,
                "max_drawdown_allowed_pct": self.max_paper_drawdown_pct,
            },
            "passed": self.passed(
                paper_trades_count, paper_days_count, total_pnl=total_pnl, max_drawdown_pct=max_drawdown_pct
            ),
        }
