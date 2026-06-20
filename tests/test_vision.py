"""Tests for the Vision Agent (rule-based chart pattern analysis)."""

from __future__ import annotations

import pytest

from agents.vision import (
    LOOKBACK_LEVELS,
    PATTERN_MIN_CONSECUTIVE,
    SUPPORT_RESISTANCE_BINS,
    VisionAgent,
    VisionInput,
    _build_pattern_rationale,
    _cluster_levels,
    _detect_chart_pattern,
    _detect_resistance_levels,
    _detect_support_levels,
    _score_trend_confidence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def uptrend_candles() -> list[dict]:
    """5 candles with clear uptrend."""
    return [
        {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
        {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 1100},
        {"open": 102, "high": 105, "low": 101, "close": 104, "volume": 1200},
        {"open": 104, "high": 106, "low": 103, "close": 105, "volume": 1300},
        {"open": 105, "high": 108, "low": 104, "close": 107, "volume": 1400},
    ]


@pytest.fixture
def downtrend_candles() -> list[dict]:
    """5 candles with clear downtrend."""
    return [
        {"open": 107, "high": 108, "low": 105, "close": 106, "volume": 1400},
        {"open": 106, "high": 107, "low": 104, "close": 105, "volume": 1300},
        {"open": 105, "high": 106, "low": 102, "close": 103, "volume": 1200},
        {"open": 103, "high": 104, "low": 101, "close": 102, "volume": 1100},
        {"open": 102, "high": 103, "low": 100, "close": 101, "volume": 1000},
    ]


@pytest.fixture
def consolidation_candles() -> list[dict]:
    """5 candles in a tight range (<3%)."""
    return [
        {"open": 100, "high": 101, "low": 99.5, "close": 100.5, "volume": 1000},
        {"open": 100.5, "high": 101.5, "low": 100, "close": 101, "volume": 1100},
        {"open": 101, "high": 101.8, "low": 100.2, "close": 100.8, "volume": 1200},
        {"open": 100.8, "high": 101.3, "low": 100.1, "close": 101.2, "volume": 1300},
        {"open": 101.2, "high": 102, "low": 100.5, "close": 100.7, "volume": 1400},
    ]


@pytest.fixture
def flat_candles() -> list[dict]:
    """Only 1 candle — insufficient for pattern detection."""
    return [
        {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
    ]


# ---------------------------------------------------------------------------
# Unit tests: _cluster_levels
# ---------------------------------------------------------------------------


class TestClusterLevels:
    def test_empty_list(self):
        assert _cluster_levels([], ascending=True) == []

    def test_single_value(self):
        assert _cluster_levels([50.0], ascending=True) == [50.0]

    def test_all_same_value(self):
        assert _cluster_levels([100.0, 100.0, 100.0], ascending=True) == [100.0]

    def test_returns_sorted_ascending(self):
        prices = [10, 20, 10, 20, 10, 30, 40]
        result = _cluster_levels(prices, ascending=True)
        # Most frequent: 10 appears 3 times, 20 appears 2 times
        assert result == sorted(result)  # should be ascending

    def test_returns_sorted_descending(self):
        prices = [10, 20, 10, 20, 10, 30, 40]
        result = _cluster_levels(prices, ascending=False)
        assert result == sorted(result, reverse=True)  # should be descending


# ---------------------------------------------------------------------------
# Unit tests: _detect_support_levels / _detect_resistance_levels
# ---------------------------------------------------------------------------


class TestDetectLevels:
    def test_support_empty_candles(self):
        assert _detect_support_levels([]) == []

    def test_resistance_empty_candles(self):
        assert _detect_resistance_levels([]) == []

    def test_support_returns_levels(self, uptrend_candles):
        levels = _detect_support_levels(uptrend_candles)
        assert len(levels) > 0
        assert all(isinstance(l, float) for l in levels)

    def test_resistance_returns_levels(self, uptrend_candles):
        levels = _detect_resistance_levels(uptrend_candles)
        assert len(levels) > 0
        assert all(isinstance(l, float) for l in levels)

    def test_support_below_resistance(self, uptrend_candles):
        support = _detect_support_levels(uptrend_candles)
        resistance = _detect_resistance_levels(uptrend_candles)
        if support and resistance:
            assert max(support) < min(resistance)


# ---------------------------------------------------------------------------
# Unit tests: _detect_chart_pattern
# ---------------------------------------------------------------------------


class TestDetectChartPattern:
    def test_empty_candles_returns_flat(self):
        pattern, confidence = _detect_chart_pattern([])
        assert pattern == "flat"
        assert confidence == 0.0

    def test_insufficient_candles_returns_flat(self, flat_candles):
        pattern, confidence = _detect_chart_pattern(flat_candles)
        assert pattern == "flat"
        assert confidence == 0.0

    def test_detects_uptrend(self, uptrend_candles):
        pattern, confidence = _detect_chart_pattern(uptrend_candles)
        assert pattern == "uptrend"
        assert confidence > 0

    def test_detects_downtrend(self, downtrend_candles):
        pattern, confidence = _detect_chart_pattern(downtrend_candles)
        assert pattern == "downtrend"
        assert confidence > 0

    def test_detects_consolidation(self, consolidation_candles):
        pattern, confidence = _detect_chart_pattern(consolidation_candles)
        assert pattern == "consolidation"
        assert confidence == 60.0

    def test_candles_without_keys(self):
        candles = [{"close": 100}, {"close": 101}]
        pattern, confidence = _detect_chart_pattern(candles)
        assert pattern in ("flat", "uptrend")  # may detect if high/low exist


# ---------------------------------------------------------------------------
# Unit tests: _score_trend_confidence
# ---------------------------------------------------------------------------


class TestScoreTrendConfidence:
    def test_insufficient_data(self):
        score = _score_trend_confidence([100], [102], [99])
        assert score == 30.0

    def test_strong_trend(self):
        closes = [100, 106]  # 6% change
        highs = [102, 108]
        lows = [99, 105]
        score = _score_trend_confidence(closes, highs, lows)
        assert score > 80  # >5% move → 85

    def test_moderate_trend(self):
        closes = [100, 104]  # 4% change
        highs = [102, 106]
        lows = [99, 103]
        score = _score_trend_confidence(closes, highs, lows)
        assert 60 <= score < 80  # >3% move → 70

    def test_weak_trend(self):
        closes = [100, 101.1]  # 1.1% change → > 0.01 threshold
        highs = [102, 103]
        lows = [99, 100]
        score = _score_trend_confidence(closes, highs, lows)
        assert 50 <= score < 60  # >1% move → 55

    def test_no_trend(self):
        closes = [100, 100.5]  # 0.5% change
        highs = [102, 102.5]
        lows = [99, 99.5]
        score = _score_trend_confidence(closes, highs, lows)
        assert score == 40.0


# ---------------------------------------------------------------------------
# Unit tests: _build_pattern_rationale
# ---------------------------------------------------------------------------


class TestBuildPatternRationale:
    def test_no_levels(self):
        result = _build_pattern_rationale("uptrend", [], [])
        assert "uptrend" in result

    def test_with_support(self):
        result = _build_pattern_rationale("downtrend", [95.0, 90.0], [])
        assert "downtrend" in result
        assert "support" in result

    def test_with_resistance(self):
        result = _build_pattern_rationale("consolidation", [], [105.0, 110.0])
        assert "consolidation" in result
        assert "resistance" in result

    def test_with_both(self):
        result = _build_pattern_rationale("uptrend", [98.0], [105.0])
        assert "uptrend" in result
        assert "support" in result
        assert "resistance" in result


# ---------------------------------------------------------------------------
# VisionAgent integration tests
# ---------------------------------------------------------------------------


class TestVisionAgent:
    @pytest.mark.asyncio
    async def test_run_with_empty_data(self):
        agent = VisionAgent()
        result = await agent.run(VisionInput(symbol="BTC-USD"))
        assert result.chart_pattern is not None
        assert result.confidence >= 0
        assert isinstance(result.support_levels, list)
        assert isinstance(result.resistance_levels, list)
        assert result.available is False  # no model
        assert result.rationale is not None

    @pytest.mark.asyncio
    async def test_run_detects_uptrend(self, uptrend_candles):
        agent = VisionAgent()
        result = await agent.run(VisionInput(
            symbol="BTC-USD",
            candles=uptrend_candles,
        ))
        assert result.chart_pattern == "uptrend"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_run_detects_downtrend(self, downtrend_candles):
        agent = VisionAgent()
        result = await agent.run(VisionInput(
            symbol="BTC-USD",
            candles=downtrend_candles,
        ))
        assert result.chart_pattern == "downtrend"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_run_detects_consolidation(self, consolidation_candles):
        agent = VisionAgent()
        result = await agent.run(VisionInput(
            symbol="BTC-USD",
            candles=consolidation_candles,
        ))
        assert result.chart_pattern == "consolidation"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_run_with_model_available_no_images(self):
        """model_available=True without chart images should fall back to rule-based."""
        agent = VisionAgent(model_available=True)
        result = await agent.run(VisionInput(symbol="BTC-USD"))
        assert result.chart_pattern is not None
        assert result.available is False  # no images → no model analysis

    @pytest.mark.asyncio
    async def test_run_returns_support_and_resistance(self, uptrend_candles):
        agent = VisionAgent()
        result = await agent.run(VisionInput(
            symbol="BTC-USD",
            candles=uptrend_candles,
        ))
        assert len(result.support_levels) > 0
        assert len(result.resistance_levels) > 0
        assert all(isinstance(l, float) for l in result.support_levels)
        assert all(isinstance(l, float) for l in result.resistance_levels)

    @pytest.mark.asyncio
    async def test_run_includes_rationale(self, uptrend_candles):
        agent = VisionAgent()
        result = await agent.run(VisionInput(
            symbol="BTC-USD",
            candles=uptrend_candles,
        ))
        assert isinstance(result.rationale, str)
        assert len(result.rationale) > 0

    @pytest.mark.asyncio
    async def test_analyze_with_model_default_returns_placeholder(self):
        agent = VisionAgent(model_available=True)
        result = await agent._analyze_with_model(
            VisionInput(symbol="TEST", chart_image_urls=["http://example.com/chart.png"]),
        )
        assert "not configured" in result


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants:
    def test_lookback_levels(self):
        assert LOOKBACK_LEVELS > 0

    def test_support_resistance_bins(self):
        assert SUPPORT_RESISTANCE_BINS > 0

    def test_pattern_min_consecutive(self):
        assert PATTERN_MIN_CONSECUTIVE >= 2
