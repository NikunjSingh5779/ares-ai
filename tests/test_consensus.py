"""Tests for ConsensusEngine."""

from __future__ import annotations

from typing import Any

import pytest

from agents.consensus import ConsensusEngine

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_ma_long() -> dict[str, Any]:
    return {"direction": "long", "confidence": 85.0, "rationale": "Bullish trend"}


@pytest.fixture
def valid_quant_long() -> dict[str, Any]:
    return {"direction": "long", "confidence": 90.0, "rationale": "Momentum bullish"}


@pytest.fixture
def valid_ma_short() -> dict[str, Any]:
    return {"direction": "short", "confidence": 88.0, "rationale": "Bearish signal"}


@pytest.fixture
def valid_quant_short() -> dict[str, Any]:
    return {"direction": "short", "confidence": 82.0, "rationale": "Trend reversal"}


# ---------------------------------------------------------------------------
# ConsensusEngine Tests
# ---------------------------------------------------------------------------


class TestConsensusEngine:
    def test_both_above_80_agree_long(self, valid_ma_long: dict[str, Any], valid_quant_long: dict[str, Any]) -> None:
        """Both agents above 80%, agree on long → approved."""
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long)
        assert result["approved"] is True
        assert result["composite_confidence"] == 87.5  # (85 + 90) / 2

    def test_both_above_80_agree_short(self, valid_ma_short: dict[str, Any], valid_quant_short: dict[str, Any]) -> None:
        """Both agents above 80%, agree on short → approved."""
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_short, valid_quant_short)
        assert result["approved"] is True
        assert result["composite_confidence"] == 85.0  # (88 + 82) / 2

    def test_market_analyst_below_80(self, valid_quant_long: dict[str, Any]) -> None:
        """Market Analyst below 80% → rejected."""
        ma = {"direction": "long", "confidence": 70.0, "rationale": "Weak signal"}
        result = ConsensusEngine.evaluate("BTC-USD", ma, valid_quant_long)
        assert result["approved"] is False
        assert "confidence thresholds" in result["rationale"]

    def test_quant_below_80(self, valid_ma_long: dict[str, Any]) -> None:
        """Quant below 80% → rejected."""
        quant = {"direction": "long", "confidence": 65.0, "rationale": "Low confidence"}
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, quant)
        assert result["approved"] is False
        assert "confidence thresholds" in result["rationale"]

    def test_both_below_threshold(self) -> None:
        """Both below threshold → rejected."""
        ma = {"direction": "long", "confidence": 50.0, "rationale": "a"}
        quant = {"direction": "long", "confidence": 45.0, "rationale": "b"}
        result = ConsensusEngine.evaluate("BTC-USD", ma, quant)
        assert result["approved"] is False

    def test_agree_on_flat(self, valid_ma_long: dict[str, Any]) -> None:
        """Both confident but flat → rejected (flat is not a trade signal)."""
        ma = {"direction": "flat", "confidence": 85.0, "rationale": "No opinion"}
        quant = {"direction": "flat", "confidence": 90.0, "rationale": "No opinion"}
        result = ConsensusEngine.evaluate("BTC-USD", ma, quant)
        assert result["approved"] is False
        assert "direction" in result["rationale"].lower()

    def test_disagree_on_direction(self, valid_ma_long: dict[str, Any], valid_quant_short: dict[str, Any]) -> None:
        """Both confident but disagree on direction → rejected."""
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_short)
        assert result["approved"] is False
        assert "direction mismatch" in result["rationale"]

    def test_market_analyst_missing(self, valid_quant_long: dict[str, Any]) -> None:
        """Missing market analyst output → rejected."""
        result = ConsensusEngine.evaluate("BTC-USD", None, valid_quant_long)
        assert result["approved"] is False
        assert "Market Analyst" in result["rationale"]

    def test_quant_missing(self, valid_ma_long: dict[str, Any]) -> None:
        """Missing quant output → rejected."""
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, None)
        assert result["approved"] is False
        assert "Quant" in result["rationale"]

    def test_both_missing(self) -> None:
        """Both missing → rejected."""
        result = ConsensusEngine.evaluate("BTC-USD", None, None)
        assert result["approved"] is False
        assert "Market Analyst" in result["rationale"]
        assert "Quant" in result["rationale"]

    def test_agreement_metrics_are_present(
        self, valid_ma_long: dict[str, Any], valid_quant_long: dict[str, Any]
    ) -> None:
        """Agreement metrics contain all expected keys."""
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long)
        metrics = result["agreement_metrics"]
        assert "ma_confidence" in metrics
        assert "quant_confidence" in metrics
        assert "ma_direction" in metrics
        assert "quant_direction" in metrics
        assert "directions_agree" in metrics
        assert metrics["ma_confidence"] == 85.0
        assert metrics["quant_confidence"] == 90.0
        assert metrics["ma_direction"] == "long"
        assert metrics["quant_direction"] == "long"
        assert metrics["directions_agree"] is True

    def test_composite_confidence_average(
        self, valid_ma_long: dict[str, Any], valid_quant_long: dict[str, Any]
    ) -> None:
        """Composite confidence is the average of both."""
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long)
        assert result["composite_confidence"] == (85.0 + 90.0) / 2

    def test_composite_confidence_when_one_low(self, valid_quant_long: dict[str, Any]) -> None:
        """Composite confidence is still the average even when one is low."""
        ma = {"direction": "long", "confidence": 40.0, "rationale": "Weak"}
        result = ConsensusEngine.evaluate("BTC-USD", ma, valid_quant_long)
        assert result["composite_confidence"] == (40.0 + 90.0) / 2
        assert result["approved"] is False

    def test_edge_confidence_just_above_80(self) -> None:
        """Both just above 80% → approved when directions agree."""
        ma = {"direction": "long", "confidence": 80.5, "rationale": "Just enough"}
        quant = {"direction": "long", "confidence": 80.1, "rationale": "Barely"}
        result = ConsensusEngine.evaluate("BTC-USD", ma, quant)
        assert result["approved"] is True

    def test_edge_confidence_exactly_80(self) -> None:
        """Both exactly 80% → just meets threshold inclusive."""
        ma = {"direction": "long", "confidence": 80.0, "rationale": "Exactly 80"}
        quant = {"direction": "long", "confidence": 80.0, "rationale": "Exactly 80"}
        result = ConsensusEngine.evaluate("BTC-USD", ma, quant)
        assert result["approved"] is True

    def test_edge_confidence_just_below_80(self) -> None:
        """Both just below 80% → rejected."""
        ma = {"direction": "long", "confidence": 79.9, "rationale": "Almost there"}
        quant = {"direction": "long", "confidence": 79.5, "rationale": "Close"}
        result = ConsensusEngine.evaluate("BTC-USD", ma, quant)
        assert result["approved"] is False

    # ------------------------------------------------------------------ #
    # Vision advisory nudge tests                                        #
    # ------------------------------------------------------------------ #

    def test_vision_none_backward_compatible(
        self,
        valid_ma_long: dict[str, Any],
        valid_quant_long: dict[str, Any],
    ) -> None:
        """No vision parameter → identical result to pre-vision call."""
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long)
        assert result["approved"] is True
        assert result["composite_confidence"] == 87.5
        assert result["agreement_metrics"].get("vision_available") is False
        assert result["agreement_metrics"].get("vision_agreement") is None

    def test_vision_none_explicit(
        self,
        valid_ma_long: dict[str, Any],
        valid_quant_long: dict[str, Any],
    ) -> None:
        """vision_output=None → no nudge."""
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long, vision_output=None)
        assert result["approved"] is True
        assert result["composite_confidence"] == 87.5
        assert result["agreement_metrics"].get("vision_available") is False
        assert result["agreement_metrics"].get("vision_agreement") is None

    def test_vision_unavailable(
        self,
        valid_ma_long: dict[str, Any],
        valid_quant_long: dict[str, Any],
    ) -> None:
        """Vision available=False → no nudge."""
        vision = {"available": False, "confidence": 80.0, "chart_pattern": "uptrend"}
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long, vision_output=vision)
        assert result["approved"] is True
        assert result["composite_confidence"] == 87.5
        assert result["agreement_metrics"]["vision_available"] is False
        assert result["agreement_metrics"]["vision_agreement"] is None

    def test_vision_low_confidence(
        self,
        valid_ma_long: dict[str, Any],
        valid_quant_long: dict[str, Any],
    ) -> None:
        """Vision available but confidence below threshold → no nudge."""
        vision = {"available": True, "confidence": 50.0, "chart_pattern": "uptrend"}
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long, vision_output=vision)
        assert result["approved"] is True
        assert result["composite_confidence"] == 87.5
        assert result["agreement_metrics"]["vision_available"] is True
        assert result["agreement_metrics"]["vision_agreement"] is None

    def test_vision_agrees_long(
        self,
        valid_ma_long: dict[str, Any],
        valid_quant_long: dict[str, Any],
    ) -> None:
        """Vision uptrend agrees with long → positive nudge."""
        vision = {"available": True, "confidence": 80.0, "chart_pattern": "uptrend"}
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long, vision_output=vision)
        assert result["approved"] is True
        # composite_confidence = (85+90)/2 + 3 nudge = 90.5
        assert result["composite_confidence"] == 90.5
        assert result["agreement_metrics"]["vision_available"] is True
        assert result["agreement_metrics"]["vision_agreement"] is True

    def test_vision_disagrees_short_against_long(
        self,
        valid_ma_long: dict[str, Any],
        valid_quant_long: dict[str, Any],
    ) -> None:
        """Vision downtrend disagrees with long → negative nudge."""
        vision = {"available": True, "confidence": 80.0, "chart_pattern": "downtrend"}
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long, vision_output=vision)
        assert result["approved"] is True
        # composite_confidence = (85+90)/2 - 3 nudge = 84.5
        assert result["composite_confidence"] == 84.5
        assert result["agreement_metrics"]["vision_available"] is True
        assert result["agreement_metrics"]["vision_agreement"] is False

    def test_vision_flat_pattern_no_nudge(
        self,
        valid_ma_long: dict[str, Any],
        valid_quant_long: dict[str, Any],
    ) -> None:
        """Vision consolidation pattern → no nudge (flat maps to no direction)."""
        vision = {"available": True, "confidence": 80.0, "chart_pattern": "consolidation"}
        result = ConsensusEngine.evaluate("BTC-USD", valid_ma_long, valid_quant_long, vision_output=vision)
        assert result["approved"] is True
        assert result["composite_confidence"] == 87.5  # unchanged
        assert result["agreement_metrics"]["vision_agreement"] is None

    def test_vision_does_not_flip_rejection(
        self,
        valid_quant_long: dict[str, Any],
    ) -> None:
        """Vision agreement does NOT flip a rejection to approval."""
        ma = {"direction": "long", "confidence": 70.0, "rationale": "Low conf"}
        vision = {"available": True, "confidence": 90.0, "chart_pattern": "uptrend"}
        result = ConsensusEngine.evaluate("BTC-USD", ma, valid_quant_long, vision_output=vision)
        assert result["approved"] is False  # still rejected without confident MA
        assert "vision" not in result["rationale"].lower()  # no nudge was applied (already rejected)
