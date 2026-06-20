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
