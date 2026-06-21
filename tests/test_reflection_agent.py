"""Tests for the Reflection Agent."""

from __future__ import annotations

import pytest

from agents.reflection import ReflectionAgent, ReflectionInput


class TestReflectionAgent:
    async def test_output_structure(self) -> None:
        """Output should contain all ReflectionOutput fields."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(symbol="BTC-USD", request="Analyze")
        )
        assert "evaluation" in result
        assert "confidence_accuracy" in result
        assert "improvement_suggestions" in result
        assert "knowledge_updates" in result

    async def test_executed_trade_evaluation(self) -> None:
        """Evaluation for an executed trade."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(
                symbol="BTC-USD",
                execution_output={
                    "executed": True,
                    "fill_price": 50000.0,
                    "rationale": "Long BTC at 50k",
                },
                market_analyst_output={
                    "direction": "long",
                    "confidence": 85.0,
                    "rationale": "Bullish momentum",
                },
            )
        )
        assert "Trade executed" in result["evaluation"]
        assert result["confidence_accuracy"] >= 0
        assert len(result["improvement_suggestions"]) > 0
        assert len(result["knowledge_updates"]) > 0

    async def test_rejected_trade_evaluation(self) -> None:
        """Evaluation for a rejected trade."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(
                symbol="BTC-USD",
                execution_output={
                    "executed": False,
                    "rationale": "Risk rejected trade",
                },
                market_analyst_output={
                    "direction": "long",
                    "confidence": 50.0,
                    "rationale": "Weak signal",
                },
            )
        )
        assert "not executed" in result["evaluation"].lower()
        assert result["confidence_accuracy"] >= 0

    async def test_high_confidence_executed(self) -> None:
        """High confidence + executed = high accuracy score."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(
                symbol="BTC-USD",
                execution_output={"executed": True, "rationale": "ok"},
                market_analyst_output={
                    "direction": "long",
                    "confidence": 90.0,
                    "rationale": "Strong signal",
                },
                consensus_output={
                    "approved": True,
                    "composite_confidence": 85.0,
                    "agreement_metrics": {
                        "ma_confidence": 90.0,
                        "quant_confidence": 80.0,
                        "ma_direction": "long",
                        "quant_direction": "long",
                        "directions_agree": True,
                    },
                    "rationale": "Agreed",
                },
            )
        )
        assert result["confidence_accuracy"] >= 80.0  # high confidence → accurate

    async def test_low_confidence_not_executed(self) -> None:
        """Low confidence + not executed = high accuracy (correctly cautious)."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(
                symbol="BTC-USD",
                execution_output={"executed": False, "rationale": "No trade"},
                market_analyst_output={
                    "direction": "flat",
                    "confidence": 30.0,
                    "rationale": "Uncertain",
                },
            )
        )
        assert result["confidence_accuracy"] >= 80.0  # correctly cautious

    async def test_no_input_graceful(self) -> None:
        """Minimal input should not crash."""
        agent = ReflectionAgent()
        result = await agent.process(ReflectionInput())
        assert result["evaluation"] is not None
        assert result["confidence_accuracy"] == 0.0
        assert isinstance(result["improvement_suggestions"], list)
        assert isinstance(result["knowledge_updates"], list)

    # --- Edge case tests for _compute_confidence_accuracy ---

    async def test_consensus_approved_risk_rejected_high_confidence(self) -> None:
        """Consensus approved, high confidence, but risk rejected = high accuracy (agents correct)."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(
                symbol="BTC-USD",
                execution_output={"executed": False, "rationale": "Risk rejected: portfolio exposure limit"},
                market_analyst_output={
                    "direction": "long",
                    "confidence": 85.0,
                    "rationale": "Strong bullish",
                },
                consensus_output={
                    "approved": True,
                    "composite_confidence": 85.0,
                    "agreement_metrics": {
                        "ma_confidence": 85.0,
                        "quant_confidence": 85.0,
                        "ma_direction": "long",
                        "quant_direction": "long",
                        "directions_agree": True,
                    },
                    "rationale": "Both agents agree",
                },
            )
        )
        # Agents were correctly confident; risk correctly filtered
        assert result["confidence_accuracy"] >= 80.0

    async def test_consensus_rejected_direction_mismatch_high_confidence(self) -> None:
        """Consensus rejected (direction mismatch), high confidence, not executed = high accuracy."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(
                symbol="BTC-USD",
                execution_output={"executed": False, "rationale": "Consensus rejected"},
                market_analyst_output={
                    "direction": "long",
                    "confidence": 85.0,
                    "rationale": "Bullish",
                },
                consensus_output={
                    "approved": False,
                    "composite_confidence": 82.0,
                    "agreement_metrics": {
                        "ma_confidence": 85.0,
                        "quant_confidence": 79.0,
                        "ma_direction": "long",
                        "quant_direction": "short",
                        "directions_agree": False,
                    },
                    "rationale": "Direction mismatch",
                },
            )
        )
        # High confidence but direction mismatch correctly rejected
        assert result["confidence_accuracy"] >= 75.0

    async def test_consensus_approved_executed_high_confidence(self) -> None:
        """Consensus approved, executed, high confidence = 90 accuracy."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(
                symbol="BTC-USD",
                execution_output={"executed": True, "fill_price": 50000.0, "rationale": "ok"},
                market_analyst_output={
                    "direction": "long",
                    "confidence": 90.0,
                    "rationale": "Strong signal",
                },
                consensus_output={
                    "approved": True,
                    "composite_confidence": 88.0,
                    "agreement_metrics": {
                        "ma_confidence": 90.0,
                        "quant_confidence": 86.0,
                        "ma_direction": "long",
                        "quant_direction": "long",
                        "directions_agree": True,
                    },
                    "rationale": "Agreed",
                },
            )
        )
        assert result["confidence_accuracy"] >= 85.0

    async def test_consensus_rejected_not_executed_low_confidence(self) -> None:
        """Consensus rejected, not executed, low confidence = 90 accuracy."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(
                symbol="BTC-USD",
                execution_output={"executed": False, "rationale": "Consensus rejected"},
                market_analyst_output={
                    "direction": "flat",
                    "confidence": 40.0,
                    "rationale": "Uncertain",
                },
                consensus_output={
                    "approved": False,
                    "composite_confidence": 45.0,
                    "agreement_metrics": {
                        "ma_confidence": 40.0,
                        "quant_confidence": 50.0,
                        "ma_direction": "flat",
                        "quant_direction": "flat",
                        "directions_agree": False,
                    },
                    "rationale": "Thresholds not met",
                },
            )
        )
        assert result["confidence_accuracy"] >= 85.0

    async def test_consensus_approved_executed_low_confidence(self) -> None:
        """Consensus approved but low confidence, executed = lower accuracy."""
        agent = ReflectionAgent()
        result = await agent.process(
            ReflectionInput(
                symbol="BTC-USD",
                execution_output={"executed": True, "fill_price": 50000.0, "rationale": "ok"},
                market_analyst_output={
                    "direction": "long",
                    "confidence": 60.0,
                    "rationale": "Weak signal",
                },
                consensus_output={
                    "approved": True,
                    "composite_confidence": 65.0,
                    "agreement_metrics": {
                        "ma_confidence": 60.0,
                        "quant_confidence": 70.0,
                        "ma_direction": "long",
                        "quant_direction": "long",
                        "directions_agree": True,
                    },
                    "rationale": "Agreed",
                },
            )
        )
        # Low confidence but consensus approved and executed
        assert result["confidence_accuracy"] <= 50.0
