"""Tests for the live trading API router.

Uses FastAPI TestClient with mocked engine dependencies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    return TestClient(app)


def _make_mock_engine():
    """Create a mock engine with reasonable defaults for testing."""
    from live_trading.audit import OrderAuditor
    from live_trading.safety import KillSwitch, ModeManager, PromotionGate, TradingMode

    mock_exchange = AsyncMock()
    mock_exchange.exchange_name = "binance"
    mock_exchange.is_connected = False
    mock_exchange.connect = AsyncMock(return_value=True)
    mock_exchange.disconnect = AsyncMock()

    class FakeEngine:
        exchange = mock_exchange
        kill_switch = KillSwitch(max_drawdown_pct=15.0)
        mode_manager = ModeManager(TradingMode.HUMAN_APPROVAL)
        promotion_gate = PromotionGate(min_paper_trades=50, min_paper_days=30)
        auditor = OrderAuditor()

        is_running = False

        @property
        def is_connected(self):
            return self.exchange.is_connected

        @property
        def mode(self):
            return self.mode_manager.mode

        def set_paper_record(self, trades, days):
            pass

        @property
        def paper_record(self):
            return {
                "trades": 0,
                "days": 0,
                "promotion": {
                    "trades": {"current": 0, "required": 50},
                    "days": {"current": 0, "required": 30},
                    "passed": False,
                },
            }

        async def start(self):
            await self.exchange.connect()
            self.is_running = True
            self.exchange.is_connected = True
            return True

        async def stop(self):
            await self.exchange.disconnect()
            self.is_running = False
            self.exchange.is_connected = False
            return True

    return FakeEngine()


class TestLiveStatus:
    """GET /api/v1/live/status tests."""

    def test_status_returns_ok(self, client) -> None:
        with patch("backend.routers.live._get_engine", return_value=_make_mock_engine()):
            response = client.get("/api/v1/live/status")
        assert response.status_code == 200
        data = response.json()
        assert "running" in data
        assert "mode" in data
        assert "kill_switch" in data
        assert "exchange" in data
        assert "paper_record" in data


class TestLiveMode:
    """POST /api/v1/live/mode tests."""

    def test_set_mode_valid(self, client) -> None:
        engine = _make_mock_engine()
        engine.mode_manager.set_mode = lambda m: None
        with patch("backend.routers.live._get_engine", return_value=engine):
            response = client.post("/api/v1/live/mode", json={"mode": "semi"})
        assert response.status_code == 200
        assert response.json()["mode"] == "semi"

    def test_set_mode_invalid(self, client) -> None:
        with patch("backend.routers.live._get_engine", return_value=_make_mock_engine()):
            response = client.post("/api/v1/live/mode", json={"mode": "invalid"})
        assert response.status_code == 400
        assert "Invalid mode" in response.json()["detail"]

    def test_set_mode_blocked_when_kill_switch_active(self, client) -> None:
        engine = _make_mock_engine()
        engine.kill_switch.activate(reason="test")
        with patch("backend.routers.live._get_engine", return_value=engine):
            response = client.post("/api/v1/live/mode", json={"mode": "semi"})
        assert response.status_code == 400
        assert "kill switch" in response.json()["detail"].lower()

    def test_set_mode_auto_blocked_when_promotion_not_passed(self, client) -> None:
        engine = _make_mock_engine()
        with patch("backend.routers.live._get_engine", return_value=engine):
            response = client.post("/api/v1/live/mode", json={"mode": "auto"})
        assert response.status_code == 400
        assert "paper record" in response.json()["detail"].lower()


class TestLiveStartStop:
    """POST /api/v1/live/start and /stop tests."""

    def test_start_engine(self, client) -> None:
        engine = _make_mock_engine()
        with patch("backend.routers.live._get_engine", return_value=engine):
            response = client.post("/api/v1/live/start")
        assert response.status_code == 200
        assert response.json()["status"] == "started"

    def test_start_when_already_running(self, client) -> None:
        engine = _make_mock_engine()
        engine.is_running = True
        with patch("backend.routers.live._get_engine", return_value=engine):
            response = client.post("/api/v1/live/start")
        assert response.status_code == 200
        assert response.json()["status"] == "already_running"

    def test_stop_engine(self, client) -> None:
        engine = _make_mock_engine()
        engine.is_running = True
        with patch("backend.routers.live._get_engine", return_value=engine):
            response = client.post("/api/v1/live/stop")
        assert response.status_code == 200
        assert response.json()["status"] == "stopped"

    def test_stop_when_already_stopped(self, client) -> None:
        engine = _make_mock_engine()
        with patch("backend.routers.live._get_engine", return_value=engine):
            response = client.post("/api/v1/live/stop")
        assert response.status_code == 200
        assert response.json()["status"] == "already_stopped"


class TestKillSwitchEndpoints:
    """POST /api/v1/live/kill and /arm tests."""

    def test_activate_kill_switch(self, client) -> None:
        with patch("backend.routers.live._get_engine", return_value=_make_mock_engine()):
            response = client.post("/api/v1/live/kill", json={"reason": "manual_test"})
        assert response.status_code == 200
        assert response.json()["status"] == "kill_switch_active"

    def test_arm_kill_switch(self, client) -> None:
        with patch("backend.routers.live._get_engine", return_value=_make_mock_engine()):
            response = client.post("/api/v1/live/arm")
        assert response.status_code == 200
        assert response.json()["status"] == "kill_switch_armed"


class TestLiveDataEndpoints:
    """GET endpoints for positions, orders, audit, paper_record."""

    def test_positions(self, client) -> None:
        with patch("backend.routers.live._get_engine", return_value=_make_mock_engine()):
            response = client.get("/api/v1/live/positions")
        assert response.status_code == 200
        assert response.json() == []

    def test_orders(self, client) -> None:
        with patch("backend.routers.live._get_engine", return_value=_make_mock_engine()):
            response = client.get("/api/v1/live/orders")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_audit(self, client) -> None:
        with patch("backend.routers.live._get_engine", return_value=_make_mock_engine()):
            response = client.get("/api/v1/live/audit")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_audit_with_limit(self, client) -> None:
        with patch("backend.routers.live._get_engine", return_value=_make_mock_engine()):
            response = client.get("/api/v1/live/audit?limit=10")
        assert response.status_code == 200

    def test_paper_record(self, client) -> None:
        with patch("backend.routers.live._get_engine", return_value=_make_mock_engine()):
            response = client.get("/api/v1/live/paper_record")
        assert response.status_code == 200
        assert "trades" in response.json()
        assert "promotion" in response.json()
