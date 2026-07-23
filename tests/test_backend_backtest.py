"""Tests for the backtest API router."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.data.models import OHLCVData
from backend.main import app

client = TestClient(app)


def test_run_backtest_invalid_strategy():
    """Test that invalid strategy is rejected."""
    payload = {
        "symbol": "BTC-USD",
        "strategy": "invalid_magic_strategy",
    }
    response = client.post("/api/v1/backtest/run", json=payload)
    assert response.status_code == 400
    assert "Invalid strategy" in response.json()["detail"]


@pytest.mark.asyncio
async def test_run_backtest_success(monkeypatch):
    """Test successful backtest run using synthetic data."""
    # Create 300 synthetic candles
    candles = []
    base_price = 100.0
    for i in range(300):
        # A simple sine wave to create some movement
        price = base_price + (i % 20)
        candles.append(
            OHLCVData(
                symbol="BTC-USD",
                source="yahoo",
                interval="1d",
                timestamp=datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i),
                open=price,
                high=price * 1.05,
                low=price * 0.95,
                close=price,
                volume=1000.0,
            )
        )

    # Mock ingestor to return synthetic data
    async def mock_ingest(self, req, *args, **kwargs):
        from backend.data.models import MarketDataResult
        res = MarketDataResult(symbol=req.symbol, source=req.source, interval=req.interval)
        res.candles = candles
        return res

    monkeypatch.setattr("backend.data.ingestor.MarketDataIngestor.ingest", mock_ingest)

    payload = {
        "symbol": "BTC-USD",
        "strategy": "momentum",
        "initial_capital": 50000.0,
    }

    response = client.post("/api/v1/backtest/run", json=payload)
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["symbol"] == "BTC-USD"
    assert "metrics" in data
    assert "trades" in data
    assert "equity_curve" in data

    # We should have evaluated at least 300 - 200 = 100 candles
    # Depending on the synthetic data and _rule_based_quant, signals_generated may vary.
    assert "signals_generated" in data

    metrics = data["metrics"]
    assert metrics["initial_capital"] == 50000.0
    assert "total_return_pct" in metrics
    assert "sharpe_ratio" in metrics
    assert "max_drawdown_pct" in metrics
