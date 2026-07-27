"""Tests for safety gates — KillSwitch, ModeManager, PromotionGate."""

from __future__ import annotations

from live_trading.safety import KillSwitch, ModeManager, PromotionGate, TradingMode


class TestKillSwitch:
    """KillSwitch unit tests."""

    def test_default_not_active(self) -> None:
        ks = KillSwitch()
        assert not ks.is_active
        assert ks.triggered_by is None
        assert ks.triggered_at is None

    def test_manual_activate(self) -> None:
        ks = KillSwitch()
        ks.activate(reason="user_requested")
        assert ks.is_active
        assert ks.triggered_by == "user_requested"
        assert ks.triggered_at is not None

    def test_arm_resets_state(self) -> None:
        ks = KillSwitch()
        ks.activate(reason="test")
        ks.arm()
        assert not ks.is_active
        assert ks.triggered_by is None
        assert ks.triggered_at is None

    def test_auto_trigger_breaches_threshold(self) -> None:
        ks = KillSwitch(max_drawdown_pct=15.0)
        tripped = ks.auto_trigger(20.0)
        assert tripped
        assert ks.is_active
        assert ks.triggered_by is not None and "drawdown" in ks.triggered_by

    def test_auto_trigger_below_threshold(self) -> None:
        ks = KillSwitch(max_drawdown_pct=15.0)
        tripped = ks.auto_trigger(10.0)
        assert not tripped
        assert not ks.is_active

    def test_auto_trigger_at_exact_threshold(self) -> None:
        ks = KillSwitch(max_drawdown_pct=15.0)
        tripped = ks.auto_trigger(15.0)
        assert tripped
        assert ks.is_active

    def test_default_max_drawdown(self) -> None:
        ks = KillSwitch()
        assert ks.max_drawdown_pct == 15.0

    def test_custom_max_drawdown(self) -> None:
        ks = KillSwitch(max_drawdown_pct=10.0)
        assert ks.max_drawdown_pct == 10.0

    def test_check_passes_when_not_active(self) -> None:
        ks = KillSwitch()
        result = ks.check()
        assert result.passed
        assert not result.reason

    def test_check_fails_when_active(self) -> None:
        ks = KillSwitch()
        ks.activate(reason="emergency")
        result = ks.check()
        assert not result.passed
        assert "Kill switch active" in result.reason
        assert result.code == "kill_switch"

    def test_auto_trigger_already_active(self) -> None:
        ks = KillSwitch()
        ks.activate(reason="manual")
        # Should not re-trigger if already active
        tripped = ks.auto_trigger(20.0)
        assert not tripped
        assert ks.triggered_by == "manual"


class TestModeManager:
    """ModeManager unit tests."""

    def test_default_mode_is_human_approval(self) -> None:
        mm = ModeManager()
        assert mm.mode == TradingMode.HUMAN_APPROVAL

    def test_requires_approval_in_human_mode(self) -> None:
        mm = ModeManager(TradingMode.HUMAN_APPROVAL)
        assert mm.requires_approval()

    def test_does_not_require_approval_in_auto_mode(self) -> None:
        mm = ModeManager(TradingMode.AUTO)
        assert not mm.requires_approval()

    def test_does_not_require_approval_in_semi_mode(self) -> None:
        mm = ModeManager(TradingMode.SEMI)
        assert not mm.requires_approval()

    def test_set_mode(self) -> None:
        mm = ModeManager()
        mm.set_mode(TradingMode.AUTO)
        assert mm.mode == TradingMode.AUTO

    def test_check_blocks_in_human_approval_mode(self) -> None:
        mm = ModeManager(TradingMode.HUMAN_APPROVAL)
        result = mm.check()
        assert not result.passed
        assert "human_approval" in result.reason
        assert "confirmation required" in result.reason
        assert result.code == "mode"

    def test_check_passes_in_auto_mode(self) -> None:
        mm = ModeManager(TradingMode.AUTO)
        result = mm.check()
        assert result.passed
        assert result.reason == "Mode is auto"

    def test_check_passes_in_semi_mode(self) -> None:
        mm = ModeManager(TradingMode.SEMI)
        result = mm.check()
        assert result.passed
        assert result.reason == "Mode is semi"


class TestPromotionGate:
    """PromotionGate unit tests."""

    def test_default_min_trades(self) -> None:
        pg = PromotionGate()
        assert pg.min_paper_trades == 50

    def test_default_min_days(self) -> None:
        pg = PromotionGate()
        assert pg.min_paper_days == 30

    def test_passed_both_thresholds_met(self) -> None:
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5)
        assert pg.passed(10, 5)

    def test_fails_trades_below_minimum(self) -> None:
        pg = PromotionGate(min_paper_trades=50, min_paper_days=30)
        assert not pg.passed(25, 30)

    def test_fails_days_below_minimum(self) -> None:
        pg = PromotionGate(min_paper_trades=50, min_paper_days=30)
        assert not pg.passed(50, 10)

    def test_fails_both_below_minimum(self) -> None:
        pg = PromotionGate(min_paper_trades=50, min_paper_days=30)
        assert not pg.passed(10, 5)

    def test_passed_exactly_at_minimum(self) -> None:
        pg = PromotionGate(min_paper_trades=50, min_paper_days=30)
        assert pg.passed(50, 30)

    def test_check_returns_safety_result_passed(self) -> None:
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5)
        result = pg.check(10, 5)
        assert result.passed

    def test_check_returns_safety_result_failed(self) -> None:
        pg = PromotionGate(min_paper_trades=50, min_paper_days=30)
        result = pg.check(10, 5)
        assert not result.passed
        assert "Paper record" in result.reason
        assert "10/50" in result.reason
        assert "5/30" in result.reason

    def test_progress_returns_dict(self) -> None:
        pg = PromotionGate(min_paper_trades=50, min_paper_days=30)
        progress = pg.progress(25, 10)
        assert progress["trades"]["current"] == 25
        assert progress["trades"]["required"] == 50
        assert progress["days"]["current"] == 10
        assert progress["days"]["required"] == 30
        assert not progress["passed"]

    # --- Risk-quality thresholds -------------------------------------
    # A strategy must not be promotable purely by racking up enough trades
    # and days while carrying unacceptable risk (excessive drawdown) or a
    # net-losing paper record. Track record alone is not sufficient.

    def test_passed_ignores_risk_when_not_supplied(self) -> None:
        """Backward compatible: omitting risk metrics skips those checks."""
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5)
        assert pg.passed(10, 5)

    def test_fails_when_drawdown_exceeds_allowed(self) -> None:
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5, max_paper_drawdown_pct=20.0)
        assert not pg.passed(10, 5, max_drawdown_pct=25.0)

    def test_passes_when_drawdown_within_allowed(self) -> None:
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5, max_paper_drawdown_pct=20.0)
        assert pg.passed(10, 5, max_drawdown_pct=15.0)

    def test_fails_when_paper_record_is_net_losing(self) -> None:
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5, require_non_negative_pnl=True)
        assert not pg.passed(10, 5, total_pnl=-500.0)

    def test_passes_when_paper_record_is_profitable(self) -> None:
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5, require_non_negative_pnl=True)
        assert pg.passed(10, 5, total_pnl=500.0)

    def test_count_and_days_still_gate_even_with_good_risk_metrics(self) -> None:
        """Enough trades/days is necessary but no longer sufficient on its own,
        and good risk metrics don't let a short/thin record skip the count/days
        requirement either — both dimensions must hold."""
        pg = PromotionGate(min_paper_trades=50, min_paper_days=30, max_paper_drawdown_pct=20.0)
        assert not pg.passed(10, 5, total_pnl=1000.0, max_drawdown_pct=2.0)

    def test_check_reason_reflects_risk_failure_not_count(self) -> None:
        """Regression guard: when trades/days are satisfied but risk quality
        isn't, the failure reason must describe the actual risk failure, not
        misleadingly describe the count/days as insufficient."""
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5, max_paper_drawdown_pct=20.0)
        result = pg.check(10, 5, max_drawdown_pct=30.0)
        assert not result.passed
        assert "drawdown" in result.reason.lower()
        assert result.code == "promotion_gate"

    def test_progress_includes_risk_section(self) -> None:
        pg = PromotionGate(min_paper_trades=10, min_paper_days=5, max_paper_drawdown_pct=20.0)
        progress = pg.progress(10, 5, total_pnl=-100.0, max_drawdown_pct=25.0)
        assert progress["risk"]["total_pnl"] == -100.0
        assert progress["risk"]["max_drawdown_pct"] == 25.0
        assert not progress["passed"]
