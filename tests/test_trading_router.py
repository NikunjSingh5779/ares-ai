"""Tests for the approved-only paper execution API."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agents.state import MarketAnalystOutput, QuantOutput, RiskOutput
from backend.main import app
from backend.routers import trading
from paper_trading.engine import PortfolioSummary
from paper_trading.repository import PaperLedgerError, PaperOrderConflictError


def _summary(equity: float = 100000.0) -> PortfolioSummary:
    return PortfolioSummary(
        initial_capital=100000.0,
        cash=equity,
        total_pnl=0.0,
        total_return_pct=0.0,
        win_rate=0.0,
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        open_positions=0,
        equity=equity,
    )


def _approval(
    *,
    direction: str = "long",
    ma_confidence: float = 85.0,
    quant_confidence: float = 85.0,
    risk_approved: bool = True,
    risk_score: float = 40.0,
    max_position_size: float | None = 0.04,
    stop_loss: float | None = 48000.0,
    current_price: float | None = 50000.0,
) -> dict[str, Any]:
    bias = "bullish" if direction == "long" else "bearish"
    market = MarketAnalystOutput(
        confidence=ma_confidence,
        direction=direction,
        bias=bias,
        setup="test setup",
        entry_zone=str(current_price),
        stop_loss=str(stop_loss),
        targets=["51000"],
        invalidation="test invalidation",
        confluence="test confluence",
        indicators={"current_price": current_price} if current_price is not None else {},
        rationale="approval test",
    )
    quant = QuantOutput(
        confidence=quant_confidence,
        direction=direction,
        strategy_name="trend",
        rationale="approval test",
    )
    risk = RiskOutput(
        approved=risk_approved,
        max_position_size=max_position_size,
        stop_loss=stop_loss,
        risk_score=risk_score,
        reasons=["test"],
        rationale="approval test",
    )
    return {
        "market_analyst_output": market.model_dump(),
        "quant_output": quant.model_dump(),
        "risk_output": risk.model_dump(),
    }


def _body(
    *,
    side: str = "long",
    approval: dict[str, Any] | None = None,
    client_order_id: str = "order-1",
) -> dict[str, Any]:
    return {
        "client_order_id": client_order_id,
        "symbol": "BTC-USD",
        "side": side,
        "approval": approval or _approval(direction=side),
    }


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_ledger(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    ledger = MagicMock()
    ledger.get_summary = AsyncMock(return_value=_summary())
    ledger.execute_signal = AsyncMock(
        return_value={
            "accepted": True,
            "position_id": "position-1",
            "ledger_persisted": True,
        }
    )
    monkeypatch.setattr(trading, "get_paper_trading_ledger", lambda: ledger)
    return ledger


def test_rejects_raw_execute_body_without_approval(client: TestClient, fake_ledger: MagicMock) -> None:
    response = client.post(
        "/api/v1/execute",
        json={
            "client_order_id": "order-1",
            "symbol": "BTC-USD",
            "side": "long",
            "quantity": 1.0,
            "entry_price": 50000.0,
        },
    )

    assert response.status_code == 422
    fake_ledger.execute_signal.assert_not_awaited()


def test_rejects_missing_client_order_id(client: TestClient, fake_ledger: MagicMock) -> None:
    body = _body()
    body.pop("client_order_id")

    response = client.post("/api/v1/execute", json=body)

    assert response.status_code == 422
    fake_ledger.execute_signal.assert_not_awaited()


def test_rejects_manual_bypass_field(client: TestClient, fake_ledger: MagicMock) -> None:
    body = _body()
    body["manual"] = True

    response = client.post("/api/v1/execute", json=body)

    assert response.status_code == 422
    fake_ledger.execute_signal.assert_not_awaited()


def test_executes_only_server_derived_approved_values(client: TestClient, fake_ledger: MagicMock) -> None:
    response = client.post("/api/v1/execute", json=_body())

    assert response.status_code == 200
    assert response.json()["client_order_id"] == "order-1"
    call = fake_ledger.execute_signal.await_args.kwargs
    assert call["symbol"] == "BTC-USD"
    assert call["side"] == "long"
    assert call["quantity"] == pytest.approx(0.04)
    assert call["entry_price"] == pytest.approx(50000.0)
    assert call["stop_loss"] == pytest.approx(48000.0)
    assert call["take_profit"] is None
    assert call["strategy_name"] == "trend"
    assert call["client_order_id"] == "order-1"


@pytest.mark.parametrize("side", ["long", "short"])
def test_accepts_approved_long_and_short(
    client: TestClient,
    fake_ledger: MagicMock,
    side: str,
) -> None:
    approval = _approval(
        direction=side,
        stop_loss=48000.0 if side == "long" else 52000.0,
    )

    response = client.post("/api/v1/execute", json=_body(side=side, approval=approval))

    assert response.status_code == 200, response.text
    assert fake_ledger.execute_signal.await_args.kwargs["side"] == side


def test_rejects_low_confidence_even_if_caller_claims_approval(
    client: TestClient,
    fake_ledger: MagicMock,
) -> None:
    response = client.post("/api/v1/execute", json=_body(approval=_approval(ma_confidence=75.0)))

    assert response.status_code == 422
    assert "confidence thresholds" in response.json()["detail"]
    fake_ledger.execute_signal.assert_not_awaited()


def test_rejects_direction_mismatch(client: TestClient, fake_ledger: MagicMock) -> None:
    response = client.post(
        "/api/v1/execute",
        json=_body(side="short", approval=_approval(direction="long")),
    )

    assert response.status_code == 422
    fake_ledger.execute_signal.assert_not_awaited()


def test_rejects_risk_rejection(client: TestClient, fake_ledger: MagicMock) -> None:
    response = client.post(
        "/api/v1/execute",
        json=_body(approval=_approval(risk_approved=False)),
    )

    assert response.status_code == 422
    assert "test" in response.json()["detail"]
    fake_ledger.execute_signal.assert_not_awaited()


def test_rejects_risk_score_above_limit(client: TestClient, fake_ledger: MagicMock) -> None:
    response = client.post(
        "/api/v1/execute",
        json=_body(approval=_approval(risk_score=95.0)),
    )

    assert response.status_code == 422
    assert "Risk score" in response.json()["detail"]
    fake_ledger.execute_signal.assert_not_awaited()


def test_rejects_position_above_account_limit(client: TestClient, fake_ledger: MagicMock) -> None:
    response = client.post(
        "/api/v1/execute",
        json=_body(approval=_approval(max_position_size=0.05)),
    )

    assert response.status_code == 422
    assert "paper-account limit" in response.json()["detail"]
    fake_ledger.execute_signal.assert_not_awaited()


def test_rejects_wrong_side_stop_loss(client: TestClient, fake_ledger: MagicMock) -> None:
    response = client.post(
        "/api/v1/execute",
        json=_body(approval=_approval(stop_loss=51000.0)),
    )

    assert response.status_code == 422
    assert "stop_loss" in response.json()["detail"]
    fake_ledger.execute_signal.assert_not_awaited()


def test_rejects_missing_approved_price(client: TestClient, fake_ledger: MagicMock) -> None:
    response = client.post(
        "/api/v1/execute",
        json=_body(approval=_approval(current_price=None)),
    )

    assert response.status_code == 422
    assert "current_price" in response.json()["detail"]
    fake_ledger.execute_signal.assert_not_awaited()


def test_rejects_non_finite_approved_price(client: TestClient, fake_ledger: MagicMock) -> None:
    approval = _approval()
    approval["market_analyst_output"]["indicators"]["current_price"] = "nan"

    response = client.post("/api/v1/execute", json=_body(approval=approval))

    assert response.status_code == 422
    assert "current_price" in response.json()["detail"]
    fake_ledger.execute_signal.assert_not_awaited()


def test_duplicate_client_order_id_returns_conflict(client: TestClient, fake_ledger: MagicMock) -> None:
    fake_ledger.execute_signal = AsyncMock(side_effect=PaperOrderConflictError("already used"))

    response = client.post("/api/v1/execute", json=_body())

    assert response.status_code == 409
    assert "client_order_id" in response.json()["detail"]


def test_ledger_failure_returns_service_unavailable(client: TestClient, fake_ledger: MagicMock) -> None:
    fake_ledger.execute_signal = AsyncMock(side_effect=PaperLedgerError("database down"))

    response = client.post("/api/v1/execute", json=_body())

    assert response.status_code == 503
