"""Tests for the Memory Agent."""

from __future__ import annotations

import pytest

from agents.memory import MemoryAgent, MemoryInput


class TestMemoryAgent:
    async def test_output_structure(self) -> None:
        """Output should contain all MemoryOutput fields."""
        agent = MemoryAgent()
        result = await agent.process(
            MemoryInput(symbol="BTC-USD", request="Analyze")
        )
        assert "relevant_memories" in result
        assert "consolidated" in result
        assert "rationale" in result

    async def test_consolidated_flag(self) -> None:
        """Consolidated should be True after processing."""
        agent = MemoryAgent()
        result = await agent.process(
            MemoryInput(symbol="BTC-USD", request="test")
        )
        assert result["consolidated"] is True

    async def test_memories_from_executed_trade(self) -> None:
        """Executed trade should produce memory records."""
        agent = MemoryAgent()
        result = await agent.process(
            MemoryInput(
                symbol="BTC-USD",
                request="Trade BTC",
                execution_output={
                    "executed": True,
                    "fill_price": 50000.0,
                    "order_id": "abc",
                    "rationale": "Long BTC at 50k",
                },
                market_analyst_output={
                    "direction": "long",
                    "confidence": 85.0,
                    "rationale": "Bullish momentum",
                },
            )
        )
        assert len(result["relevant_memories"]) >= 2  # trade + analyst + request
        trade_memories = [m for m in result["relevant_memories"] if m["type"] == "trade"]
        assert len(trade_memories) == 1
        assert trade_memories[0]["importance"] == 7.0

    async def test_memories_from_rejected_trade(self) -> None:
        """Rejected trade should still produce memory records."""
        agent = MemoryAgent()
        result = await agent.process(
            MemoryInput(
                symbol="BTC-USD",
                request="Trade BTC",
                execution_output={
                    "executed": False,
                    "rationale": "Risk rejected",
                },
                market_analyst_output={
                    "direction": "long",
                    "confidence": 85.0,
                    "rationale": "Bullish",
                },
            )
        )
        assert len(result["relevant_memories"]) > 0
        trade_memories = [m for m in result["relevant_memories"] if m["type"] == "trade"]
        assert trade_memories[0]["importance"] == 3.0  # lower importance for rejected

    async def test_memories_include_risk_rejection(self) -> None:
        """Risk rejection should create a separate memory."""
        agent = MemoryAgent()
        result = await agent.process(
            MemoryInput(
                symbol="BTC-USD",
                execution_output={
                    "executed": False,
                    "rationale": "Risk rejected",
                },
                risk_output={
                    "approved": False,
                    "risk_score": 90.0,
                    "reasons": ["High volatility"],
                    "rationale": "Risk too high",
                },
            )
        )
        agent_memories = [m for m in result["relevant_memories"] if m["type"] == "agent_output"]
        assert any("Risk rejected" in m["content"] for m in agent_memories)

    async def test_empty_input_graceful(self) -> None:
        """Empty/Minimal input should not crash."""
        agent = MemoryAgent()
        result = await agent.process(MemoryInput())
        assert result["consolidated"] is True
        assert isinstance(result["relevant_memories"], list)
        assert isinstance(result["rationale"], str)
