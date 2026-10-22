"""Tests for the Prometheus-backed JSON metrics endpoint."""

from __future__ import annotations

from prometheus_client import REGISTRY
from starlette.testclient import TestClient

from backend.core.metrics import (
    get_metrics_snapshot,
    record_agent_fallback,
    record_agent_run,
    record_live_order,
    set_kill_switch_active,
)


def test_get_metrics_snapshot_reflects_recorded_metrics() -> None:
    """The JSON snapshot is derived from the same counters Prometheus serves."""
    set_kill_switch_active(False)
    before = get_metrics_snapshot()

    record_agent_run("snapshot-test", "success")
    record_agent_run("snapshot-test", "success")
    record_agent_run("snapshot-test", "error")
    record_agent_fallback("snapshot-test", "primary-model", "fallback-model")
    record_live_order("filled")
    set_kill_switch_active(True)

    try:
        after = get_metrics_snapshot()
        assert after["agent_runs_total"] == before["agent_runs_total"] + 3
        assert after["agent_errors_total"] == before["agent_errors_total"] + 1
        assert after["agent_fallbacks_total"] == before["agent_fallbacks_total"] + 1
        assert after["live_orders_total"] == before["live_orders_total"] + 1
        assert after["kill_switch_active"] is True
    finally:
        set_kill_switch_active(False)


def test_metrics_endpoint_returns_prometheus_snapshot() -> None:
    """GET /api/v1/metrics returns the JSON summary, not the last pipeline run."""
    from backend.main import app

    set_kill_switch_active(False)
    record_agent_run("endpoint-test", "success")
    record_agent_run("endpoint-test", "error")
    record_agent_fallback("endpoint-test", "primary-model", "fallback-model")
    record_live_order("filled")

    with TestClient(app) as client:
        response = client.get("/api/v1/metrics")

    assert response.status_code == 200
    data = response.json()
    assert data["agent_runs_total"] >= 2
    assert data["agent_errors_total"] >= 1
    assert data["agent_fallbacks_total"] >= 1
    assert data["live_orders_total"] >= 1
    assert data["http_requests_total"] >= 0
    assert data["kill_switch_active"] is False


def test_metrics_endpoint_does_not_read_last_state(monkeypatch) -> None:
    """The metrics endpoint must not depend on the analysis pipeline global."""
    from backend.main import app

    def _boom():
        message = "/api/v1/metrics read _last_state"
        raise AssertionError(message)

    monkeypatch.setattr("backend.routers.monitoring.get_last_state", _boom)

    with TestClient(app) as client:
        response = client.get("/api/v1/metrics")

    assert response.status_code == 200


def test_prometheus_endpoint_exposes_registered_metrics() -> None:
    """The public /metrics mount serves the real Prometheus exposition format."""
    from backend.main import app

    record_agent_run("prometheus-endpoint-test", "success")

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "ares_agents_runs_total" in response.text
    assert "ares_requests_total" in response.text
    assert REGISTRY.get_sample_value(
        "ares_agents_runs_total",
        {"agent": "prometheus-endpoint-test", "status": "success"},
    )
