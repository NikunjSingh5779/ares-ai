"""Tests for RiskAgent."""
from __future__ import annotations

from unittest.mock import AsyncMock
from datetime import UTC, datetime

import pytest

from agents.base import AgentContext
from agents.indicators import compute_all_indicators
from agents.risk import (
    MAX_POSITION_SIZE_PCT,
    MAX_RISK_SCORE,
    RiskAgent,
    RiskInput,
    _compute_risk_score,
    _parse_risk_response,
    _rule_based_risk,
    build_risk_prompt,
)
from agents.router import RouterResult
from backend.data.models import OHLCVData


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_candles() -> list[OHLCVData]:
    """60 daily candles with moderate volatility."""
    candles = []
    for i in range(60):
        price = 100.0 + i * 0.2 + (i % 8 - 4) * 0.5
        candles.append(OHLCVData(
            symbol="BTC-USD", source="yahoo", interval="1d",
            timestamp=datetime(2024, 1, 1, tzinfo=UTC).replace(day=min(28, 1 + i)),
            open=price, high=price * 1.015, low=price * 0.985,
            close=price, volume=2000.0,
        ))
    return candles


@pytest.fixture
def sample_indicators(sample_candles: list[OHLCVData]) -> dict:
    return compute_all_indicators(sample_candles)


# ---------------------------------------------------------------------------
# Prompt Builder Tests
# ---------------------------------------------------------------------------

class TestBuildRiskPrompt:
    def test_returns_message_list(self, sample_indicators: dict) -> None:
        messages = build_risk_prompt("BTC-USD", sample_indicators, None, None, None, 100000.0)
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_prompt_contains_risk_criteria(self) -> None:
        messages = build_risk_prompt("BTC-USD", {}, None, None, None, 100000.0)
        system = messages[0]["content"]
        assert "position size" in system.lower()
        assert "stop loss" in system.lower()
        assert "volatility" in system.lower()

    def test_user_prompt_contains_symbol_and_portfolio(self, sample_indicators: dict) -> None:
        messages = build_risk_prompt("ETH-USD", sample_indicators, None, None, None, 50000.0)
        content = messages[1]["content"]
        assert "ETH-USD" in content
        assert "50,000" in content

    def test_includes_upstream_signals(self, sample_indicators: dict) -> None:
        ma = {"direction": "long", "confidence": 85.0, "rationale": "Bullish"}
        quant = {"direction": "long", "confidence": 90.0, "rationale": "Momentum"}
        consensus = {"approved": True, "composite_confidence": 87.5, "rationale": "Agreed"}
        messages = build_risk_prompt("BTC-USD", sample_indicators, ma, quant, consensus, 100000.0)
        content = messages[1]["content"]
        assert "Market Analyst" in content
        assert "Quant" in content
        assert "Consensus" in content

    def test_handles_empty_indicators(self) -> None:
        messages = build_risk_prompt("BTC-USD", {}, None, None, None, 100000.0)
        assert len(messages) == 2


# ---------------------------------------------------------------------------
# Rule-Based Risk Tests
# ---------------------------------------------------------------------------

class TestRuleBasedRisk:
    def test_returns_risk_structure(self, sample_indicators: dict) -> None:
        """Baseline: valid output structure."""
        result = _rule_based_risk("BTC-USD", sample_indicators)
        assert "approved" in result
        assert "max_position_size" in result
        assert "stop_loss" in result
        assert "risk_score" in result
        assert "reasons" in result
        assert "rationale" in result
        assert isinstance(result["approved"], bool)
        assert isinstance(result["reasons"], list)

    def test_approved_with_good_signal(self, sample_indicators: dict) -> None:
        """High confidence, consensus approved → approved."""
        result = _rule_based_risk(
            "BTC-USD", sample_indicators,
            market_analyst_output={"direction": "long", "confidence": 85.0},
            quant_output={"direction": "long", "confidence": 90.0},
            consensus_output={"approved": True, "composite_confidence": 87.5},
        )
        assert result["approved"] is True
        assert result["risk_score"] <= MAX_RISK_SCORE

    def test_rejected_without_consensus(self, sample_indicators: dict) -> None:
        """No consensus output and low confidence → rejected."""
        result = _rule_based_risk(
            "BTC-USD", sample_indicators,
            market_analyst_output={"direction": "long", "confidence": 65.0},
            quant_output={"direction": "long", "confidence": 60.0},
            consensus_output=None,
        )
        assert result["approved"] is False
        assert "did not pass consensus" in result["rationale"]

    def test_rejected_when_consensus_not_approved(self, sample_indicators: dict) -> None:
        """Consensus output says not approved → rejected."""
        result = _rule_based_risk(
            "BTC-USD", sample_indicators,
            consensus_output={"approved": False, "composite_confidence": 50.0},
        )
        assert result["approved"] is False

    def test_with_empty_candles(self) -> None:
        """No market data → should still return a result (rejected)."""
        result = _rule_based_risk("BTC-USD", {})
        assert isinstance(result["approved"], bool)
        assert isinstance(result["risk_score"], (int, float))

    def test_negative_portfolio_value_clamped(self, sample_indicators: dict) -> None:
        """Negative portfolio value should be handled gracefully."""
        result = _rule_based_risk("BTC-USD", sample_indicators, portfolio_value=-1000.0)
        assert isinstance(result["approved"], bool)
        assert result["risk_score"] >= 0

    def test_position_size_calculation(self, sample_indicators: dict) -> None:
        """Position size should follow 2% rule."""
        consensus = {"approved": True, "composite_confidence": 85.0}
        ma = {"direction": "long", "confidence": 85.0}
        quant = {"direction": "long", "confidence": 90.0}
        portfolio = 100000.0
        result = _rule_based_risk(
            "BTC-USD", sample_indicators,
            ma, quant, consensus, portfolio,
        )
        # 2% of $100k = $2000, at ~$100 = ~20 units
        if result["max_position_size"] is not None:
            price = sample_indicators.get("current_price", 100)
            expected_max = round(portfolio * (MAX_POSITION_SIZE_PCT / 100.0) / price, 4)
            assert result["max_position_size"] == expected_max


# ---------------------------------------------------------------------------
# Risk Score Computation
# ---------------------------------------------------------------------------

class TestComputeRiskScore:
    def test_base_score(self) -> None:
        score = _compute_risk_score({}, 100000.0)
        assert score == 30.0  # base

    def test_high_volatility_adds_score(self) -> None:
        score = _compute_risk_score({"atr_14": 10.0, "current_price": 100.0}, 100000.0)
        assert score > 30.0

    def test_extreme_rsi_adds_score(self) -> None:
        score = _compute_risk_score({"rsi_14": 85.0}, 100000.0)
        assert score >= 40.0

    def test_borderline_rsi_adds_less(self) -> None:
        score_borderline = _compute_risk_score({"rsi_14": 75.0}, 100000.0)
        score_extreme = _compute_risk_score({"rsi_14": 85.0}, 100000.0)
        assert score_borderline < score_extreme

    def test_neutral_trend_adds_score(self) -> None:
        score = _compute_risk_score({"trend": "neutral"}, 100000.0)
        assert score >= 40.0

    def test_small_portfolio_adds_score(self) -> None:
        score = _compute_risk_score({}, 5000.0)
        assert score >= 40.0

    def test_score_capped_at_100(self) -> None:
        score = _compute_risk_score(
            {"atr_14": 20.0, "current_price": 100.0, "rsi_14": 90.0, "trend": "neutral"},
            5000.0,
        )
        assert score <= 100.0

    def test_multiple_factors_accumulate(self) -> None:
        """Multiple risk factors should accumulate but cap at 100."""
        score = _compute_risk_score(
            {"atr_14": 10.0, "current_price": 100.0, "rsi_14": 25.0, "trend": "neutral"},
            5000.0,
        )
        assert 30 <= score <= 100


# ---------------------------------------------------------------------------
# LLM Response Parser Tests
# ---------------------------------------------------------------------------

class TestParseRiskResponse:
    def test_parses_valid_json(self) -> None:
        response = (
            '{"approved": true, "max_position_size": 25.0, "stop_loss": 95.0, '
            '"risk_score": 45.0, "reasons": ["Low volatility"], '
            '"rationale": "Risk approved"}'
        )
        fallback = {"approved": False, "max_position_size": None, "stop_loss": None,
                     "risk_score": 100.0, "reasons": [], "rationale": "fb"}
        result = _parse_risk_response(response, fallback)
        assert result["approved"] is True
        assert result["max_position_size"] == 25.0
        assert result["stop_loss"] == 95.0
        assert result["risk_score"] == 45.0
        assert "Low volatility" in result["reasons"]

    def test_handles_markdown_fenced_json(self) -> None:
        response = '```json\n{"approved": false, "risk_score": 90.0, "rationale": "Too risky"}\n```'
        fallback = {"approved": False, "max_position_size": None, "stop_loss": None,
                     "risk_score": 100.0, "reasons": [], "rationale": "fb"}
        result = _parse_risk_response(response, fallback)
        assert result["approved"] is False
        assert result["risk_score"] == 90.0

    def test_fallback_on_invalid_json(self) -> None:
        response = "not json"
        fallback = {"approved": False, "max_position_size": None, "stop_loss": None,
                     "risk_score": 80.0, "reasons": [], "rationale": "fb"}
        result = _parse_risk_response(response, fallback)
        assert result == fallback

    def test_fallback_on_missing_required(self) -> None:
        response = '{"risk_score": 50}'  # missing approved and rationale
        fallback = {"approved": False, "max_position_size": None, "stop_loss": None,
                     "risk_score": 100.0, "reasons": [], "rationale": "fb"}
        result = _parse_risk_response(response, fallback)
        assert result == fallback

    def test_clamps_risk_score_above_100(self) -> None:
        response = '{"approved": true, "risk_score": 200.0, "rationale": "over max"}'
        fallback = {"approved": False, "max_position_size": None, "stop_loss": None,
                     "risk_score": 100.0, "reasons": [], "rationale": "fb"}
        result = _parse_risk_response(response, fallback)
        assert result["risk_score"] == 100.0

    def test_clamps_risk_score_below_0(self) -> None:
        response = '{"approved": true, "risk_score": -50.0, "rationale": "under min"}'
        fallback = {"approved": False, "max_position_size": None, "stop_loss": None,
                     "risk_score": 100.0, "reasons": [], "rationale": "fb"}
        result = _parse_risk_response(response, fallback)
        assert result["risk_score"] == 0.0

    def test_empty_response_uses_fallback(self) -> None:
        fallback = {"approved": False, "max_position_size": None, "stop_loss": None,
                     "risk_score": 100.0, "reasons": [], "rationale": "fb"}
        result = _parse_risk_response("", fallback)
        assert result == fallback

    def test_none_response_uses_fallback(self) -> None:
        fallback = {"approved": False, "max_position_size": None, "stop_loss": None,
                     "risk_score": 100.0, "reasons": [], "rationale": "fb"}
        result = _parse_risk_response(None, fallback)
        assert result == fallback


# ---------------------------------------------------------------------------
# RiskAgent Integration Tests
# ---------------------------------------------------------------------------

class TestRiskAgentProcess:
    @pytest.mark.asyncio
    async def test_returns_valid_structure(self, sample_candles: list[OHLCVData]) -> None:
        """Agent returns valid risk output with pre-fetched candles."""
        router = AsyncMock()
        router.execute.return_value = RouterResult()

        agent = RiskAgent(router=router)
        result = await agent.run(RiskInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))

        assert hasattr(result, "approved")
        assert hasattr(result, "max_position_size")
        assert hasattr(result, "stop_loss")
        assert hasattr(result, "risk_score")
        assert hasattr(result, "reasons")
        assert hasattr(result, "rationale")
        assert isinstance(result.approved, bool)
        assert isinstance(result.reasons, list)
        assert 0 <= result.risk_score <= 100

    @pytest.mark.asyncio
    async def test_with_empty_candles(self) -> None:
        """Empty candles should still produce a result."""
        router = AsyncMock()
        agent = RiskAgent(router=router)
        result = await agent.run(RiskInput(symbol="BTC-USD", candles=[]))
        assert isinstance(result.approved, bool)
        assert 0 <= result.risk_score <= 100

    @pytest.mark.asyncio
    async def test_rejected_with_no_consensus(self, sample_candles: list[OHLCVData]) -> None:
        """No consensus output → rejected in rule-based fallback."""
        router = AsyncMock()
        agent = RiskAgent(router=router)
        result = await agent.run(RiskInput(
            symbol="BTC-USD",
            candles=sample_candles,
            consensus_output={"approved": False, "composite_confidence": 0.0},
        ))
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_llm_success_parsed(self, sample_candles: list[OHLCVData]) -> None:
        """Mocked LLM returns valid risk output."""
        router = AsyncMock()
        llm_response = RouterResult()
        llm_response.success = True
        llm_response.response = {
            "choices": [{
                "message": {
                    "content": (
                        '{"approved": true, "max_position_size": 20.0, "stop_loss": 95.0, '
                        '"risk_score": 35.0, "reasons": ["Good setup"], '
                        '"rationale": "Risk within acceptable range"}'
                    ),
                }
            }],
            "model": "test-model",
            "usage": {"total_tokens": 100},
        }
        llm_response.model_used = "test-model"
        router.execute.return_value = llm_response

        ctx = AgentContext(model_preferences={"model_chain": ["test-model"]})
        agent = RiskAgent(router=router, context=ctx)
        result = await agent.run(RiskInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))

        assert result.approved is True
        assert result.risk_score == 35.0
        assert "Good setup" in result.reasons

    @pytest.mark.asyncio
    async def test_llm_failure_fallthrough(self, sample_candles: list[OHLCVData]) -> None:
        """LLM fails → rule-based fallback used."""
        router = AsyncMock()
        router.execute.return_value = RouterResult()  # success=False by default

        ctx = AgentContext(model_preferences={"model_chain": ["test-model"]})
        agent = RiskAgent(router=router, context=ctx)
        result = await agent.run(RiskInput(
            symbol="BTC-USD",
            candles=sample_candles,
        ))

        assert isinstance(result.approved, bool)
        assert 0 <= result.risk_score <= 100
        assert isinstance(result.reasons, list)


# ---------------------------------------------------------------------------
# RiskInput Validation
# ---------------------------------------------------------------------------

class TestRiskInput:
    def test_valid_input(self) -> None:
        inp = RiskInput(symbol="BTC-USD")
        assert inp.symbol == "BTC-USD"
        assert inp.interval == "1d"
        assert inp.lookback == 100
        assert inp.candles is None
        assert inp.portfolio_value == 100000.0
        assert inp.current_positions == {}

    def test_with_candles(self, sample_candles: list[OHLCVData]) -> None:
        inp = RiskInput(symbol="BTC-USD", candles=sample_candles)
        assert inp.candles is not None
        assert len(inp.candles) == 60

    def test_with_upstream_outputs(self) -> None:
        inp = RiskInput(
            symbol="BTC-USD",
            market_analyst_output={"direction": "long", "confidence": 85.0},
            quant_output={"direction": "long", "confidence": 90.0},
            consensus_output={"approved": True, "composite_confidence": 87.5},
        )
        assert inp.market_analyst_output["direction"] == "long"
        assert inp.quant_output["confidence"] == 90.0
        assert inp.consensus_output["approved"] is True

    def test_custom_portfolio_value(self) -> None:
        inp = RiskInput(symbol="BTC-USD", portfolio_value=50000.0)
        assert inp.portfolio_value == 50000.0
