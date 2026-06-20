"""Tests for the Journal Agent."""

from __future__ import annotations

import pytest

from agents.journal import JournalAgent, JournalInput


class TestJournalAgent:
    async def test_output_structure(self) -> None:
        """Output should contain all JournalOutput fields."""
        agent = JournalAgent()
        result = await agent.process(
            JournalInput(symbol="BTC-USD", request="Analyze BTC")
        )
        assert "entry_id" in result
        assert "mistakes" in result
        assert "lessons" in result
        assert "rationale" in result

    async def test_executed_trade_entry(self) -> None:
        """Journal entry for an executed trade."""
        agent = JournalAgent()
        result = await agent.process(
            JournalInput(
                symbol="BTC-USD",
                request="Trade BTC",
                execution_output={
                    "executed": True,
                    "fill_price": 50500.0,
                    "order_id": "abc-123",
                    "rationale": "Executed long",
                },
                market_analyst_output={
                    "direction": "long",
                    "confidence": 85.0,
                    "rationale": "Bullish",
                },
            )
        )
        assert result["entry_id"] is not None
        assert "executed" in result["rationale"].lower()
        assert result["mistakes"] == []  # no errors

    async def test_rejected_trade_mistakes(self) -> None:
        """Journal captures mistakes from rejected trade."""
        agent = JournalAgent()
        result = await agent.process(
            JournalInput(
                symbol="BTC-USD",
                request="Trade BTC",
                execution_output={
                    "executed": False,
                    "rationale": "Risk agent rejected trade",
                },
                market_analyst_output={
                    "direction": "long",
                    "confidence": 85.0,
                    "rationale": "Bullish",
                },
                risk_output={
                    "approved": False,
                    "risk_score": 85.0,
                    "reasons": ["Risk score too high"],
                    "rationale": "Rejected",
                },
            )
        )
        assert len(result["mistakes"]) > 0
        assert any("risk" in m.lower() for m in result["mistakes"])

    async def test_errors_detected(self) -> None:
        """Errors in the pipeline are captured as mistakes."""
        agent = JournalAgent()
        result = await agent.process(
            JournalInput(
                symbol="BTC-USD",
                errors=[{"agent": "market_analyst", "error": "API timeout"}],
            )
        )
        assert len(result["mistakes"]) > 0
        assert any("API timeout" in m for m in result["mistakes"])

    async def test_lessons_extracted(self) -> None:
        """Lessons should always be populated."""
        agent = JournalAgent()
        result = await agent.process(
            JournalInput(symbol="BTC-USD", request="test")
        )
        assert len(result["lessons"]) > 0
        assert isinstance(result["lessons"], list)

    async def test_empty_input_graceful(self) -> None:
        """Empty/Minimal input should not crash."""
        agent = JournalAgent()
        result = await agent.process(JournalInput())
        assert result["entry_id"] is not None
        assert isinstance(result["mistakes"], list)
        assert isinstance(result["lessons"], list)
        assert isinstance(result["rationale"], str)
