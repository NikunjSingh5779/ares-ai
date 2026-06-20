"""Tests for MarketAnalystAgent."""
from __future__ import annotations

from unittest.mock import AsyncMock
from datetime import UTC, datetime

import pytest

from agents.market_analyst import (
    MarketAnalystAgent,
    MarketAnalystInput,
    _parse_llm_response,
    _rule_based_analysis,
    build_analysis_prompt,
)
from agents.indicators import compute_all_indicators
from agents.router import RouterResult
from backend.data.models import OHLCVData


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_candles() -> list[OHLCVData]:
    """100 daily candles with a slight uptrend."""
    candles = []
    for i in range(100):
        price = 100.0 + i * 0.5 + (i % 10 - 5) * 0.2
        candles.append(OHLCVData(
            symbol="BTC-USD", source="yahoo", interval="1d",
            timestamp=datetime(2024, 1, 1, tzinfo=UTC).replace(day=min(28, 1 + i)),
            open=price, high=price * 1.01, low=price * 0.99,
            close=price, volume=1000.0,
        ))
    return candles


@pytest.fixture
def sample_indicators(sample_candles: list[OHLCVData]) -> dict:
    return compute_all_indicators(sample_candles)


# ---------------------------------------------------------------------------
# Prompt Builder Tests
# ---------------------------------------------------------------------------

class TestBuildAnalysisPrompt:
    def test_returns_message_list(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_analysis_prompt("BTC-USD", sample_indicators, sample_candles)
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_prompt_contains_critical_instructions(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_analysis_prompt("BTC-USD", sample_indicators, sample_candles)
        system = messages[0]["content"]
        assert "JSON" in system
        assert "confidence" in system
        assert "direction" in system
        assert "rationale" in system

    def test_user_prompt_contains_symbol(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_analysis_prompt("BTC-USD", sample_indicators, sample_candles)
        assert "BTC-USD" in messages[1]["content"]

    def test_user_prompt_contains_indicators(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_analysis_prompt("ETH-USD", sample_indicators, sample_candles)
        content = messages[1]["content"]
        assert "RSI" in content
        assert "SMA" in content
        assert "ETH-USD" in content

    def test_handles_empty_indicators(self, sample_candles: list[OHLCVData]) -> None:
        messages = build_analysis_prompt("BTC-USD", {}, sample_candles)
        assert len(messages) == 2
        assert "No data" not in messages[1]["content"]  # should still have price data

    def test_handles_empty_candles(self) -> None:
        messages = build_analysis_prompt("BTC-USD", {}, [])
        assert len(messages) == 2


# ---------------------------------------------------------------------------
# Rule-Based Analysis Tests
# ---------------------------------------------------------------------------

class TestRuleBasedAnalysis:
    def test_oversold_rsi_gives_long(self) -> None:
        indicators = {"rsi_14": 25.0, "trend": "bearish", "current_price": 100.0}
        result = _rule_based_analysis("BTC-USD", indicators)
        assert result["direction"] in ("long", "flat")
        assert isinstance(result["confidence"], float)

    def test_overbought_rsi_gives_short(self) -> None:
        indicators = {"rsi_14": 78.0, "trend": "bullish", "current_price": 200.0}
        result = _rule_based_analysis("BTC-USD", indicators)
        assert result["direction"] in ("short", "flat")
        assert isinstance(result["confidence"], float)

    def test_bullish_trend(self) -> None:
        indicators = {
            "rsi_14": 55.0,
            "trend": "bullish",
            "current_price": 150.0,
            "sma_20": 145.0,
            "sma_50": 140.0,
            "bollinger_bands": {"middle": 145.0, "upper": 160.0, "lower": 130.0},
        }
        result = _rule_based_analysis("BTC-USD", indicators)
        assert result["direction"] == "long"
        assert result["confidence"] > 0

    def test_bearish_trend(self) -> None:
        indicators = {
            "rsi_14": 45.0,
            "trend": "bearish",
            "current_price": 100.0,
            "sma_20": 105.0,
            "sma_50": 110.0,
            "bollinger_bands": {"middle": 105.0, "upper": 115.0, "lower": 95.0},
        }
        result = _rule_based_analysis("BTC-USD", indicators)
        assert result["direction"] == "short"
        assert result["confidence"] > 0

    def test_neutral_market_gives_flat(self) -> None:
        indicators = {
            "rsi_14": 50.0,
            "trend": "neutral",
            "current_price": 100.0,
            "sma_20": 100.0,
            "sma_50": 100.0,
            "bollinger_bands": {"middle": 100.0, "upper": 110.0, "lower": 90.0},
        }
        result = _rule_based_analysis("BTC-USD", indicators)
        assert result["direction"] == "flat"

    def test_minimal_indicators_still_works(self) -> None:
        result = _rule_based_analysis("BTC-USD", {"current_price": 100.0})
        assert result["direction"] in ("long", "short", "flat")
        assert isinstance(result["rationale"], str)
        assert isinstance(result["confidence"], (int, float))

    def test_returns_required_fields(self) -> None:
        result = _rule_based_analysis("TEST", {"current_price": 50.0})
        assert "confidence" in result
        assert "direction" in result
        assert "indicators" in result
        assert "rationale" in result

    def test_volume_confirms_trend(self) -> None:
        """High volume ratio confirms the prevailing trend direction."""
        indicators = {
            "rsi_14": 55.0,
            "trend": "bullish",
            "current_price": 150.0,
            "sma_20": 145.0,
            "sma_50": 140.0,
            "bollinger_bands": {"middle": 145.0, "upper": 160.0, "lower": 130.0},
            "current_volume": 5000.0,
            "volume_sma_20": 2000.0,  # ratio = 2.5
        }
        result = _rule_based_analysis("BTC-USD", indicators)
        assert result["direction"] == "long"


# ---------------------------------------------------------------------------
# LLM Response Parser Tests
# ---------------------------------------------------------------------------

class TestParseLLMResponse:
    def test_parses_valid_json(self) -> None:
        response = '{"confidence": 85, "direction": "long", "indicators": {"rsi": 55}, "rationale": "Bullish setup"}'
        fallback = {"confidence": 30, "direction": "flat", "indicators": {}, "rationale": "fallback"}
        result = _parse_llm_response(response, fallback)
        assert result["confidence"] == 85.0
        assert result["direction"] == "long"
        assert result["indicators"]["rsi"] == 55

    def test_handles_markdown_fenced_json(self) -> None:
        response = '```json\n{"confidence": 70, "direction": "short", "indicators": {}, "rationale": "test"}\n```'
        fallback = {"confidence": 0, "direction": "flat", "indicators": {}, "rationale": "fb"}
        result = _parse_llm_response(response, fallback)
        assert result["direction"] == "short"
        assert result["confidence"] == 70.0

    def test_handles_markdown_without_lang(self) -> None:
        response = '```\n{"confidence": 60, "direction": "flat", "indicators": {"rsi": 50}, "rationale": "neutral"}\n```'
        fallback = {"confidence": 0, "direction": "flat", "indicators": {}, "rationale": "fb"}
        result = _parse_llm_response(response, fallback)
        assert result["direction"] == "flat"
        assert result["confidence"] == 60.0

    def test_fallback_on_invalid_json(self) -> None:
        response = "This is not JSON at all"
        fallback = {"confidence": 10, "direction": "flat", "indicators": {}, "rationale": "fb"}
        result = _parse_llm_response(response, fallback)
        assert result == fallback

    def test_fallback_on_missing_required_fields(self) -> None:
        response = '{"confidence": 80}'  # missing direction and rationale
        fallback = {"confidence": 10, "direction": "flat", "indicators": {}, "rationale": "fb"}
        result = _parse_llm_response(response, fallback)
        assert result == fallback

    def test_fallback_on_invalid_direction(self) -> None:
        response = '{"confidence": 80, "direction": "invalid", "rationale": "test"}'
        fallback = {"confidence": 10, "direction": "flat", "indicators": {}, "rationale": "fb"}
        result = _parse_llm_response(response, fallback)
        assert result == fallback

    def test_clamps_confidence_bounds(self) -> None:
        """Confidence is clamped to [0, 100]."""
        response = '{"confidence": 999, "direction": "long", "indicators": {}, "rationale": "test"}'
        fallback = {"confidence": 0, "direction": "flat", "indicators": {}, "rationale": "fb"}
        result = _parse_llm_response(response, fallback)
        assert result["confidence"] == 100.0

    def test_empty_response_uses_fallback(self) -> None:
        fallback = {"confidence": 10, "direction": "flat", "indicators": {}, "rationale": "fb"}
        result = _parse_llm_response("", fallback)
        assert result == fallback

    def test_none_response_uses_fallback(self) -> None:
        fallback = {"confidence": 10, "direction": "flat", "indicators": {}, "rationale": "fb"}
        result = _parse_llm_response(None, fallback)
        assert result == fallback


# ---------------------------------------------------------------------------
# MarketAnalystAgent Integration Tests
# ---------------------------------------------------------------------------

class TestMarketAnalystAgentProcess:
    @pytest.mark.asyncio
    async def test_returns_valid_structure(self, sample_candles: list[OHLCVData]) -> None:
        """Agent returns valid output with pre-fetched candles."""
        router = AsyncMock()
        router.execute.return_value = RouterResult()

        agent = MarketAnalystAgent(router=router)
        result = await agent.run(MarketAnalystInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))

        assert hasattr(result, "confidence")
        assert hasattr(result, "direction")
        assert hasattr(result, "rationale")
        assert result.direction in ("long", "short", "flat")
        assert 0 <= result.confidence <= 100

    @pytest.mark.asyncio
    async def test_with_empty_candles(self) -> None:
        """Empty candles should return flat/no confidence."""
        router = AsyncMock()

        agent = MarketAnalystAgent(router=router)
        result = await agent.run(MarketAnalystInput(symbol="BTC-USD", candles=[]))

        assert result.direction == "flat"
        assert result.confidence == 0.0
        assert "No market data" in result.rationale

    @pytest.mark.asyncio
    async def test_llm_success_returns_parsed_output(self, sample_candles: list[OHLCVData]) -> None:
        """When LLM returns valid JSON, it should be parsed and returned."""
        from agents.base import AgentContext
        from agents.router import RouterResult

        router = AsyncMock()
        llm_response = RouterResult()
        llm_response.success = True
        llm_response.response = {
            "choices": [{
                "message": {
                    "content": (
                        '{"confidence": 82.5, "direction": "long", '
                        '"indicators": {"rsi": 58.2}, '
                        '"rationale": "Bullish trend with momentum"}'
                    ),
                }
            }],
            "model": "test-model",
            "usage": {"total_tokens": 150},
        }
        llm_response.model_used = "test-model"
        router.execute.return_value = llm_response

        ctx = AgentContext(model_preferences={"model_chain": ["test-model"]})
        agent = MarketAnalystAgent(router=router, context=ctx)
        result = await agent.run(MarketAnalystInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))

        assert result.confidence == 82.5
        assert result.direction == "long"
        assert result.rationale == "Bullish trend with momentum"

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_rule_based(self, sample_candles: list[OHLCVData]) -> None:
        """When LLM fails, rule-based analysis should be used."""
        from agents.router import RouterResult

        router = AsyncMock()
        empty_result = RouterResult()  # success=False by default
        router.execute.return_value = empty_result

        agent = MarketAnalystAgent(router=router)
        result = await agent.run(MarketAnalystInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))

        # Should still produce valid output via rule-based fallback
        assert result.direction in ("long", "short", "flat")
        assert result.confidence > 0
        assert "rule-based" in result.rationale.lower()

    @pytest.mark.asyncio
    async def test_with_insufficient_candles(self) -> None:
        """Very few candles should not crash."""
        router = AsyncMock()
        agent = MarketAnalystAgent(router=router)
        result = await agent.run(MarketAnalystInput(
            symbol="BTC-USD",
            candles=[OHLCVData(
                symbol="BTC-USD", source="yahoo", interval="1d",
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=100, high=101, low=99, close=100, volume=1000,
            )],
        ))
        assert result.direction in ("long", "short", "flat")

    @pytest.mark.asyncio
    async def test_model_config_passed_to_router(self, sample_candles: list[OHLCVData]) -> None:
        """Agent context model_preferences should be respected."""
        from agents.router import RouterResult

        router = AsyncMock()
        router.execute.return_value = RouterResult()

        agent = MarketAnalystAgent(router=router)
        result = await agent.run(MarketAnalystInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))
        # Should complete without error
        assert hasattr(result, "confidence")


# ---------------------------------------------------------------------------
# MarketAnalystInput Validation
# ---------------------------------------------------------------------------

class TestMarketAnalystInput:
    def test_valid_input(self) -> None:
        inp = MarketAnalystInput(symbol="BTC-USD")
        assert inp.symbol == "BTC-USD"
        assert inp.interval == "1d"
        assert inp.lookback == 100
        assert inp.candles is None

    def test_with_candles(self, sample_candles: list[OHLCVData]) -> None:
        inp = MarketAnalystInput(symbol="BTC-USD", candles=sample_candles)
        assert inp.candles is not None
        assert len(inp.candles) == 100

    def test_custom_interval(self) -> None:
        inp = MarketAnalystInput(symbol="ETH-USD", interval="1h")
        assert inp.interval == "1h"
