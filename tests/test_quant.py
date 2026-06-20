"""Tests for QuantAgent."""
from __future__ import annotations

from unittest.mock import AsyncMock
from datetime import UTC, datetime

import pytest

from agents.quant import (
    QuantAgent,
    QuantInput,
    _build_breakout_signal,
    _build_mean_reversion_signal,
    _build_momentum_signal,
    _build_neutral_signal,
    _build_trend_following_signal,
    _detect_breakout,
    _detect_mean_reversion,
    _detect_momentum,
    _detect_trend_following,
    _parse_quant_response,
    _rule_based_quant,
    build_quant_prompt,
    _volume_ratio,
    _atr_ratio,
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

class TestBuildQuantPrompt:
    def test_returns_message_list(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_quant_prompt("BTC-USD", sample_indicators, sample_candles)
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_prompt_contains_strategies(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_quant_prompt("BTC-USD", sample_indicators, sample_candles)
        system = messages[0]["content"]
        for strategy in ("momentum", "mean_reversion", "trend_following", "breakout", "neutral"):
            assert strategy in system

    def test_system_prompt_contains_quant_fields(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_quant_prompt("BTC-USD", sample_indicators, sample_candles)
        system = messages[0]["content"]
        assert "expected_return" in system
        assert "strategy_name" in system
        assert "params" in system

    def test_user_prompt_contains_symbol(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_quant_prompt("BTC-USD", sample_indicators, sample_candles)
        assert "BTC-USD" in messages[1]["content"]

    def test_user_prompt_contains_indicators(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_quant_prompt("ETH-USD", sample_indicators, sample_candles)
        content = messages[1]["content"]
        assert "RSI" in content
        assert "ATR" in content
        assert "Bollinger" in content

    def test_includes_strategy_hint(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        messages = build_quant_prompt("BTC-USD", sample_indicators, sample_candles, strategy_hint="momentum")
        assert "momentum" in messages[1]["content"]

    def test_includes_market_analyst_context(self, sample_candles: list[OHLCVData], sample_indicators: dict) -> None:
        ma_result = {"direction": "long", "confidence": 80.0, "rationale": "Bullish trend"}
        messages = build_quant_prompt(
            "BTC-USD", sample_indicators, sample_candles,
            market_analyst_result=ma_result,
        )
        content = messages[1]["content"]
        assert "Market Analyst" in content
        assert "long" in content
        assert "80.0" in content

    def test_handles_empty_candles(self) -> None:
        messages = build_quant_prompt("BTC-USD", {}, [])
        assert len(messages) == 2


# ---------------------------------------------------------------------------
# Helper Tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_atr_ratio_with_valid_data(self) -> None:
        result = _atr_ratio({"atr_14": 5.0, "current_price": 100.0})
        assert result == 5.0  # 5/100 * 100 = 5%

    def test_atr_ratio_with_zero_price(self) -> None:
        assert _atr_ratio({"atr_14": 5.0, "current_price": 0}) is None

    def test_atr_ratio_missing_atr(self) -> None:
        assert _atr_ratio({"current_price": 100.0}) is None

    def test_volume_ratio_with_valid_data(self) -> None:
        result = _volume_ratio({"current_volume": 5000.0, "volume_sma_20": 2000.0})
        assert result == 2.5

    def test_volume_ratio_zero_average(self) -> None:
        assert _volume_ratio({"current_volume": 5000.0, "volume_sma_20": 0}) is None

    def test_volume_ratio_missing_data(self) -> None:
        assert _volume_ratio({"current_volume": 5000.0}) is None


# ---------------------------------------------------------------------------
# Strategy Detector Tests
# ---------------------------------------------------------------------------

class TestStrategyDetectors:
    def test_detect_momentum_bullish(self) -> None:
        assert _detect_momentum({"sma_20": 150.0, "sma_50": 140.0, "rsi_14": 55.0})

    def test_detect_momentum_bearish(self) -> None:
        assert _detect_momentum({"sma_20": 140.0, "sma_50": 150.0, "rsi_14": 45.0})

    def test_detect_momentum_no_crossover(self) -> None:
        assert not _detect_momentum({"sma_20": 150.0, "sma_50": 150.0, "rsi_14": 55.0})

    def test_detect_momentum_extreme_rsi(self) -> None:
        assert not _detect_momentum({"sma_20": 150.0, "sma_50": 140.0, "rsi_14": 75.0})

    def test_detect_momentum_missing_data(self) -> None:
        assert not _detect_momentum({"sma_20": 150.0})

    def test_detect_mean_reversion_oversold(self) -> None:
        assert _detect_mean_reversion({"rsi_14": 25.0})

    def test_detect_mean_reversion_overbought(self) -> None:
        assert _detect_mean_reversion({"rsi_14": 75.0})

    def test_detect_mean_reversion_neutral(self) -> None:
        assert not _detect_mean_reversion({"rsi_14": 50.0})

    def test_detect_mean_reversion_missing_data(self) -> None:
        assert not _detect_mean_reversion({})

    def test_detect_trend_following_bullish(self) -> None:
        assert _detect_trend_following({"trend": "bullish", "macd": {"histogram": 1.0}})

    def test_detect_trend_following_bearish(self) -> None:
        assert _detect_trend_following({"trend": "bearish", "macd": {"histogram": -1.0}})

    def test_detect_trend_following_neutral_trend(self) -> None:
        assert not _detect_trend_following({"trend": "neutral", "macd": {"histogram": 1.0}})

    def test_detect_trend_following_no_histogram(self) -> None:
        assert not _detect_trend_following({"trend": "bullish", "macd": {}})

    def test_detect_breakout_high_volume_upper(self) -> None:
        assert _detect_breakout({
            "current_price": 160.0,
            "current_volume": 5000.0,
            "volume_sma_20": 2000.0,
            "bollinger_bands": {"upper": 155.0, "lower": 130.0},
        })

    def test_detect_breakout_high_volume_lower(self) -> None:
        assert _detect_breakout({
            "current_price": 125.0,
            "current_volume": 5000.0,
            "volume_sma_20": 2000.0,
            "bollinger_bands": {"upper": 155.0, "lower": 130.0},
        })

    def test_detect_breakout_low_volume(self) -> None:
        assert not _detect_breakout({
            "current_price": 160.0,
            "current_volume": 2000.0,
            "volume_sma_20": 2000.0,
            "bollinger_bands": {"upper": 155.0, "lower": 130.0},
        })

    def test_detect_breakout_no_bb(self) -> None:
        assert not _detect_breakout({"current_price": 160.0, "current_volume": 5000.0, "volume_sma_20": 2000.0})


# ---------------------------------------------------------------------------
# Signal Builder Tests
# ---------------------------------------------------------------------------

class TestSignalBuilders:
    def test_momentum_signal_has_required_fields(self) -> None:
        signal = _build_momentum_signal({
            "sma_20": 150.0, "sma_50": 140.0, "rsi_14": 55.0,
            "current_price": 150.0, "atr_14": 3.0,
        })
        assert signal["direction"] in ("long", "short")
        assert 0 <= signal["confidence"] <= 100
        assert signal["expected_return"] is None or signal["expected_return"] > 0
        assert signal["strategy_name"] == "momentum"
        assert isinstance(signal["params"], dict)
        assert isinstance(signal["rationale"], str)

    def test_mean_reversion_signal_oversold(self) -> None:
        signal = _build_mean_reversion_signal({
            "rsi_14": 25.0, "current_price": 100.0,
            "bollinger_bands": {"middle": 110.0, "upper": 120.0, "lower": 100.0},
        })
        assert signal["direction"] == "long"
        assert signal["strategy_name"] == "mean_reversion"

    def test_mean_reversion_signal_overbought(self) -> None:
        signal = _build_mean_reversion_signal({
            "rsi_14": 78.0, "current_price": 100.0,
            "bollinger_bands": {"middle": 90.0, "upper": 100.0, "lower": 80.0},
        })
        assert signal["direction"] == "short"
        assert signal["strategy_name"] == "mean_reversion"

    def test_trend_following_signal_bullish(self) -> None:
        signal = _build_trend_following_signal({
            "trend": "bullish", "current_price": 150.0, "atr_14": 3.0,
            "macd": {"macd": 2.0, "signal": 1.5, "histogram": 0.5},
        })
        assert signal["direction"] == "long"
        assert signal["strategy_name"] == "trend_following"

    def test_trend_following_signal_bearish(self) -> None:
        signal = _build_trend_following_signal({
            "trend": "bearish", "current_price": 100.0, "atr_14": 3.0,
            "macd": {"macd": -2.0, "signal": -1.5, "histogram": -0.5},
        })
        assert signal["direction"] == "short"
        assert signal["strategy_name"] == "trend_following"

    def test_breakout_signal_upper(self) -> None:
        signal = _build_breakout_signal({
            "current_price": 160.0, "current_volume": 5000.0, "volume_sma_20": 2000.0,
            "bollinger_bands": {"upper": 155.0, "lower": 130.0, "middle": 142.5},
        })
        assert signal["direction"] == "short"
        assert signal["strategy_name"] == "breakout"

    def test_breakout_signal_lower(self) -> None:
        signal = _build_breakout_signal({
            "current_price": 125.0, "current_volume": 5000.0, "volume_sma_20": 2000.0,
            "bollinger_bands": {"upper": 155.0, "lower": 130.0, "middle": 142.5},
        })
        assert signal["direction"] == "long"
        assert signal["strategy_name"] == "breakout"

    def test_neutral_signal(self) -> None:
        signal = _build_neutral_signal({})
        assert signal["direction"] == "flat"
        assert signal["confidence"] == 20.0
        assert signal["expected_return"] is None
        assert signal["strategy_name"] == "neutral"


# ---------------------------------------------------------------------------
# Rule-Based Analysis Tests
# ---------------------------------------------------------------------------

class TestRuleBasedQuant:
    def test_momentum_is_detected_when_bullish(self) -> None:
        indicators = {
            "sma_20": 145.0, "sma_50": 140.0, "rsi_14": 55.0,
            "current_price": 145.0, "atr_14": 3.0,
        }
        result = _rule_based_quant("BTC-USD", indicators)
        assert result["strategy_name"] in ("momentum", "neutral")

    def test_mean_reversion_on_oversold(self) -> None:
        indicators = {
            "rsi_14": 25.0, "current_price": 100.0, "trend": "bearish",
            "bollinger_bands": {"middle": 110.0, "upper": 120.0, "lower": 100.0},
        }
        result = _rule_based_quant("BTC-USD", indicators)
        assert result["strategy_name"] in ("mean_reversion",)

    def test_mean_reversion_on_overbought(self) -> None:
        indicators = {
            "rsi_14": 78.0, "current_price": 100.0, "trend": "bullish",
            "bollinger_bands": {"middle": 90.0, "upper": 100.0, "lower": 80.0},
        }
        result = _rule_based_quant("BTC-USD", indicators)
        assert result["strategy_name"] in ("mean_reversion",)

    def test_trend_following_with_confirmation(self) -> None:
        indicators = {
            "trend": "bullish", "current_price": 150.0, "atr_14": 3.0,
            "macd": {"macd": 2.0, "signal": 1.5, "histogram": 0.5},
        }
        result = _rule_based_quant("BTC-USD", indicators)
        assert result["strategy_name"] in ("trend_following", "momentum")

    def test_breakout_with_high_volume(self) -> None:
        indicators = {
            "current_price": 160.0, "current_volume": 5000.0, "volume_sma_20": 2000.0,
            "bollinger_bands": {"upper": 155.0, "lower": 130.0, "middle": 142.5},
            "trend": "neutral",
        }
        result = _rule_based_quant("BTC-USD", indicators)
        assert result["strategy_name"] == "breakout"

    def test_strategy_hint_preferred(self) -> None:
        indicators = {
            "sma_20": 145.0, "sma_50": 140.0, "rsi_14": 55.0,
            "current_price": 145.0, "atr_14": 3.0,
            "trend": "bullish",
            "macd": {"macd": 2.0, "signal": 1.5, "histogram": 0.5},
        }
        result = _rule_based_quant("BTC-USD", indicators, strategy_hint="trend_following")
        assert result["strategy_name"] == "trend_following"

    def test_strategy_hint_no_match_falls_to_best(self) -> None:
        indicators = {
            "rsi_14": 25.0, "current_price": 100.0, "trend": "bearish",
            "bollinger_bands": {"middle": 110.0, "upper": 120.0, "lower": 100.0},
        }
        result = _rule_based_quant("BTC-USD", indicators, strategy_hint="breakout")
        # breakout won't trigger, falls back to next best
        assert result["strategy_name"] in ("mean_reversion",)

    def test_neutral_fallback_with_minimal_data(self) -> None:
        result = _rule_based_quant("BTC-USD", {"current_price": 100.0})
        assert result["direction"] == "flat"
        assert result["strategy_name"] == "neutral"
        assert result["confidence"] == 20.0

    def test_returns_quant_fields(self) -> None:
        result = _rule_based_quant("BTC-USD", {"current_price": 100.0})
        assert "confidence" in result
        assert "direction" in result
        assert "expected_return" in result
        assert "strategy_name" in result
        assert "params" in result
        assert "rationale" in result


# ---------------------------------------------------------------------------
# LLM Response Parser Tests
# ---------------------------------------------------------------------------

class TestParseQuantResponse:
    def test_parses_valid_json(self) -> None:
        response = (
            '{"confidence": 75, "direction": "long", "expected_return": 2.5, '
            '"strategy_name": "momentum", "params": {"lookback": 20}, '
            '"rationale": "Strong momentum signal"}'
        )
        fallback = {"confidence": 20, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fallback"}
        result = _parse_quant_response(response, fallback)
        assert result["confidence"] == 75.0
        assert result["direction"] == "long"
        assert result["expected_return"] == 2.5
        assert result["strategy_name"] == "momentum"
        assert result["params"]["lookback"] == 20

    def test_handles_markdown_fenced_json(self) -> None:
        response = '```json\n{"confidence": 70, "direction": "short", "expected_return": null, "strategy_name": "mean_reversion", "params": {}, "rationale": "test"}\n```'
        fallback = {"confidence": 0, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fb"}
        result = _parse_quant_response(response, fallback)
        assert result["direction"] == "short"
        assert result["strategy_name"] == "mean_reversion"

    def test_fallback_on_invalid_json(self) -> None:
        response = "This is not JSON"
        fallback = {"confidence": 10, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fb"}
        result = _parse_quant_response(response, fallback)
        assert result == fallback

    def test_fallback_on_missing_required_fields(self) -> None:
        response = '{"confidence": 80}'  # missing direction, rationale
        fallback = {"confidence": 10, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fb"}
        result = _parse_quant_response(response, fallback)
        assert result == fallback

    def test_fallback_on_invalid_direction(self) -> None:
        response = '{"confidence": 80, "direction": "invalid", "rationale": "test"}'
        fallback = {"confidence": 10, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fb"}
        result = _parse_quant_response(response, fallback)
        assert result == fallback

    def test_clamps_confidence(self) -> None:
        response = '{"confidence": 999, "direction": "long", "rationale": "test"}'
        fallback = {"confidence": 0, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fb"}
        result = _parse_quant_response(response, fallback)
        assert result["confidence"] == 100.0

    def test_validates_strategy_name(self) -> None:
        """Invalid strategy defaults to neutral."""
        response = '{"confidence": 80, "direction": "long", "rationale": "test", "strategy_name": "invalid_strat"}'
        fallback = {"confidence": 10, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fb"}
        result = _parse_quant_response(response, fallback)
        assert result["strategy_name"] == "neutral"

    def test_validates_expected_return(self) -> None:
        """Non-numeric expected_return becomes None."""
        response = '{"confidence": 80, "direction": "long", "expected_return": "not_a_number", "rationale": "test"}'
        fallback = {"confidence": 10, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fb"}
        result = _parse_quant_response(response, fallback)
        assert result["expected_return"] is None

    def test_empty_response_uses_fallback(self) -> None:
        fallback = {"confidence": 10, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fb"}
        result = _parse_quant_response("", fallback)
        assert result == fallback

    def test_none_response_uses_fallback(self) -> None:
        fallback = {"confidence": 10, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {}, "rationale": "fb"}
        result = _parse_quant_response(None, fallback)
        assert result == fallback

    def test_merges_params(self) -> None:
        """LLM params merge over fallback params."""
        response = '{"confidence": 80, "direction": "long", "rationale": "test", "params": {"lookback": 30}}'
        fallback = {"confidence": 10, "direction": "flat", "expected_return": None,
                     "strategy_name": "neutral", "params": {"risk_per_trade_pct": 2.0}, "rationale": "fb"}
        result = _parse_quant_response(response, fallback)
        assert result["params"]["lookback"] == 30
        assert result["params"]["risk_per_trade_pct"] == 2.0


# ---------------------------------------------------------------------------
# QuantAgent Integration Tests
# ---------------------------------------------------------------------------

class TestQuantAgentProcess:
    @pytest.mark.asyncio
    async def test_returns_valid_structure(self, sample_candles: list[OHLCVData]) -> None:
        """Agent returns valid output with pre-fetched candles."""
        router = AsyncMock()
        router.execute.return_value = RouterResult()

        agent = QuantAgent(router=router)
        result = await agent.run(QuantInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))

        assert hasattr(result, "confidence")
        assert hasattr(result, "direction")
        assert hasattr(result, "strategy_name")
        assert hasattr(result, "expected_return")
        assert hasattr(result, "params")
        assert hasattr(result, "rationale")
        assert result.direction in ("long", "short", "flat")
        assert 0 <= result.confidence <= 100
        assert result.strategy_name in ("momentum", "mean_reversion", "trend_following", "breakout", "neutral")
        assert isinstance(result.params, dict)

    @pytest.mark.asyncio
    async def test_with_empty_candles(self) -> None:
        """Empty candles should return flat/neutral."""
        router = AsyncMock()
        agent = QuantAgent(router=router)
        result = await agent.run(QuantInput(symbol="BTC-USD", candles=[]))

        assert result.direction == "flat"
        assert result.confidence == 0.0
        assert result.strategy_name == "neutral"
        assert "No market data" in result.rationale

    @pytest.mark.asyncio
    async def test_llm_success_returns_parsed_output(self, sample_candles: list[OHLCVData]) -> None:
        """When LLM returns valid JSON, it should be parsed and returned."""
        from agents.base import AgentContext

        router = AsyncMock()
        llm_response = RouterResult()
        llm_response.success = True
        llm_response.response = {
            "choices": [{
                "message": {
                    "content": (
                        '{"confidence": 82.5, "direction": "long", '
                        '"expected_return": 3.2, "strategy_name": "momentum", '
                        '"params": {"lookback": 20, "stop_loss_pct": 5.0}, '
                        '"rationale": "Bullish momentum with strong volume"}'
                    ),
                }
            }],
            "model": "test-model",
            "usage": {"total_tokens": 150},
        }
        llm_response.model_used = "test-model"
        router.execute.return_value = llm_response

        ctx = AgentContext(model_preferences={"model_chain": ["test-model"]})
        agent = QuantAgent(router=router, context=ctx)
        result = await agent.run(QuantInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))

        assert result.confidence == 82.5
        assert result.direction == "long"
        assert result.expected_return == 3.2
        assert result.strategy_name == "momentum"
        assert result.params.get("lookback") == 20
        assert "momentum" in result.rationale

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_rule_based(self, sample_candles: list[OHLCVData]) -> None:
        """When LLM fails, rule-based analysis should be used."""
        from agents.base import AgentContext

        router = AsyncMock()
        empty_result = RouterResult()  # success=False by default
        router.execute.return_value = empty_result

        ctx = AgentContext(model_preferences={"model_chain": ["test-model"]})
        agent = QuantAgent(router=router, context=ctx)
        result = await agent.run(QuantInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))

        assert result.direction in ("long", "short", "flat")
        assert result.confidence > 0
        assert result.strategy_name in ("momentum", "mean_reversion", "trend_following", "breakout", "neutral")

    @pytest.mark.asyncio
    async def test_with_insufficient_candles(self) -> None:
        """Very few candles should not crash."""
        router = AsyncMock()
        agent = QuantAgent(router=router)
        result = await agent.run(QuantInput(
            symbol="BTC-USD",
            candles=[OHLCVData(
                symbol="BTC-USD", source="yahoo", interval="1d",
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=100, high=101, low=99, close=100, volume=1000,
            )],
        ))
        assert result.direction in ("long", "short", "flat")

    @pytest.mark.asyncio
    async def test_strategy_hint_fallthrough(self, sample_candles: list[OHLCVData]) -> None:
        """Strategy hint in input is passed to fallback when LLM unavailable."""
        from agents.base import AgentContext

        router = AsyncMock()
        router.execute.return_value = RouterResult()

        ctx = AgentContext(model_preferences={"model_chain": ["test-model"]})
        agent = QuantAgent(router=router, context=ctx)
        result = await agent.run(QuantInput(
            symbol="BTC-USD",
            candles=sample_candles,
            strategy="trend_following",
        ))
        assert result.direction in ("long", "short", "flat")


# ---------------------------------------------------------------------------
# QuantInput Validation
# ---------------------------------------------------------------------------

class TestQuantInput:
    def test_valid_input(self) -> None:
        inp = QuantInput(symbol="BTC-USD")
        assert inp.symbol == "BTC-USD"
        assert inp.interval == "1d"
        assert inp.lookback == 100
        assert inp.candles is None
        assert inp.strategy is None

    def test_with_candles(self, sample_candles: list[OHLCVData]) -> None:
        inp = QuantInput(symbol="BTC-USD", candles=sample_candles)
        assert inp.candles is not None
        assert len(inp.candles) == 100

    def test_with_strategy_hint(self) -> None:
        inp = QuantInput(symbol="BTC-USD", strategy="momentum")
        assert inp.strategy == "momentum"

    def test_with_market_analyst_result(self) -> None:
        inp = QuantInput(symbol="BTC-USD", market_analyst_result={"direction": "long"})
        assert inp.market_analyst_result == {"direction": "long"}
