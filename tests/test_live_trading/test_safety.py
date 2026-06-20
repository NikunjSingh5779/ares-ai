"""Tests for safety gates — KillSwitch, ModeManager, PromotionGate."""

from __future__ import annotations

import pytest

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
        assert "drawdown" in ks.triggered_by

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

    def test_check_does_not_block(self) -> None:
        mm = ModeManager()
        result = mm.check()
        assert result.passed


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
