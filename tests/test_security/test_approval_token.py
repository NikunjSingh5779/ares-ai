"""Tests for signed, expiring trade approval tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from jose import jwt

from agents.state import MarketAnalystOutput, QuantOutput, RiskOutput
from backend.core.security import (
    APPROVAL_TOKEN_AUDIENCE,
    APPROVAL_TOKEN_ISSUER,
    APPROVAL_TOKEN_TYPE,
    ApprovalTokenError,
    approval_payload_hash,
    create_access_token,
    create_trade_approval_token,
    verify_trade_approval_token,
)
from backend.schemas.trading import TradeApproval
from configs.settings import settings

_SECRET = "approval-test-secret"


@pytest.fixture(autouse=True)
def _configure_signing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", _SECRET)


def _approval(*, risk_score: float = 40.0) -> TradeApproval:
    return TradeApproval(
        market_analyst_output=MarketAnalystOutput(
            confidence=85.0,
            direction="long",
            bias="bullish",
            setup="test setup",
            entry_zone="50000",
            stop_loss="48000",
            targets=["51000"],
            invalidation="test invalidation",
            confluence="test confluence",
            indicators={"current_price": 50000.0},
            rationale="approval test",
        ),
        quant_output=QuantOutput(
            confidence=85.0,
            direction="long",
            strategy_name="trend",
            rationale="approval test",
        ),
        risk_output=RiskOutput(
            approved=True,
            max_position_size=0.04,
            stop_loss=48000.0,
            risk_score=risk_score,
            reasons=["test"],
            rationale="approval test",
        ),
    )


def test_round_trip_binds_symbol_side_and_payload() -> None:
    approval = _approval()

    issued = create_trade_approval_token(symbol="BTC-USD", side="long", approval=approval)
    claims = verify_trade_approval_token(issued.token)

    assert claims.symbol == "BTC-USD"
    assert claims.side == "long"
    assert claims.approval_hash == approval_payload_hash(approval)
    assert claims.jti
    assert claims.expires_at > datetime.now(UTC)
    assert issued.expires_at == claims.expires_at


def test_hash_is_stable_across_equivalent_payloads() -> None:
    approval = _approval()

    assert approval_payload_hash(approval) == approval_payload_hash(approval.model_dump())
    assert approval_payload_hash(approval) != approval_payload_hash(_approval(risk_score=41.0))


def test_rejects_expired_token() -> None:
    issued = create_trade_approval_token(
        symbol="BTC-USD",
        side="long",
        approval=_approval(),
        expires_delta=timedelta(seconds=-1),
    )

    with pytest.raises(ApprovalTokenError, match="invalid or expired"):
        verify_trade_approval_token(issued.token)


def test_rejects_token_signed_with_a_different_key(monkeypatch: pytest.MonkeyPatch) -> None:
    issued = create_trade_approval_token(symbol="BTC-USD", side="long", approval=_approval())
    monkeypatch.setattr(settings, "jwt_secret_key", "different-approval-secret")

    with pytest.raises(ApprovalTokenError, match="invalid or expired"):
        verify_trade_approval_token(issued.token)


def test_rejects_access_token() -> None:
    access_token = create_access_token(data={"sub": "operator@example.com", "role": "admin"})

    with pytest.raises(ApprovalTokenError, match="invalid or expired"):
        verify_trade_approval_token(access_token)


def test_rejects_token_with_wrong_audience() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "typ": APPROVAL_TOKEN_TYPE,
            "iss": APPROVAL_TOKEN_ISSUER,
            "aud": "some-other-service",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": "test-jti",
            "symbol": "BTC-USD",
            "side": "long",
            "approval_hash": approval_payload_hash(_approval()),
        },
        _SECRET,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(ApprovalTokenError, match="invalid or expired"):
        verify_trade_approval_token(token)


def test_rejects_token_with_wrong_type() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "typ": "access",
            "iss": APPROVAL_TOKEN_ISSUER,
            "aud": APPROVAL_TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": "test-jti",
            "symbol": "BTC-USD",
            "side": "long",
            "approval_hash": approval_payload_hash(_approval()),
        },
        _SECRET,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(ApprovalTokenError, match="not a trade approval token"):
        verify_trade_approval_token(token)


def test_rejects_missing_or_malformed_claims() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "typ": APPROVAL_TOKEN_TYPE,
            "iss": APPROVAL_TOKEN_ISSUER,
            "aud": APPROVAL_TOKEN_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": "test-jti",
            "symbol": "BTC-USD",
            "side": "flat",
            "approval_hash": "not-a-hash",
        },
        _SECRET,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(ApprovalTokenError, match="valid side"):
        verify_trade_approval_token(token)


@pytest.mark.parametrize("secret", ["", "changeme_in_production"])
def test_refuses_to_issue_or_verify_with_a_default_secret(monkeypatch: pytest.MonkeyPatch, secret: str) -> None:
    issued = create_trade_approval_token(symbol="BTC-USD", side="long", approval=_approval())
    monkeypatch.setattr(settings, "jwt_secret_key", secret)

    with pytest.raises(ApprovalTokenError, match="JWT_SECRET_KEY"):
        create_trade_approval_token(symbol="BTC-USD", side="long", approval=_approval())
    with pytest.raises(ApprovalTokenError, match="JWT_SECRET_KEY"):
        verify_trade_approval_token(issued.token)


def test_claims_are_not_confused_with_a_login_token() -> None:
    issued = create_trade_approval_token(symbol="BTC-USD", side="long", approval=_approval())
    decoded: dict[str, Any] = jwt.decode(
        issued.token,
        _SECRET,
        algorithms=[settings.jwt_algorithm],
        audience=APPROVAL_TOKEN_AUDIENCE,
    )

    assert decoded["typ"] == APPROVAL_TOKEN_TYPE
    assert decoded["aud"] == APPROVAL_TOKEN_AUDIENCE
    assert decoded["iss"] == APPROVAL_TOKEN_ISSUER
    assert "role" not in decoded


def test_approval_token_cannot_authenticate_a_normal_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """An approval capability must not double as an API credential."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from backend.core.dependencies import verify_auth

    monkeypatch.setattr(settings, "api_secret_key", "test-api-secret")
    issued = create_trade_approval_token(symbol="BTC-USD", side="long", approval=_approval())
    app = FastAPI()

    @app.get("/protected")
    async def protected(user: str = Depends(verify_auth)) -> dict[str, str]:
        return {"user": user}

    with TestClient(app) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {issued.token}"})

    assert response.status_code == 401
    assert "cannot authenticate" in response.json()["detail"]
