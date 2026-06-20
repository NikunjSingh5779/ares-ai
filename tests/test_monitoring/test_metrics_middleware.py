"""Tests for the Prometheus metrics middleware."""
from __future__ import annotations

from starlette.testclient import TestClient

from backend.core.metrics import MetricsMiddleware


def test_metrics_middleware_records_request_count() -> None:
    """Verify the middleware increments the request counter."""
    from fastapi import FastAPI
    from prometheus_client import REGISTRY

    app = FastAPI()

    @app.get("/test-metrics")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(MetricsMiddleware)

    # Get baseline
    before = REGISTRY.get_sample_value(
        "ares_requests_total", {"method": "GET", "endpoint": "/test-metrics", "status": "200"}
    ) or 0

    with TestClient(app) as client:
        resp = client.get("/test-metrics")
        assert resp.status_code == 200

    after = REGISTRY.get_sample_value(
        "ares_requests_total", {"method": "GET", "endpoint": "/test-metrics", "status": "200"}
    ) or 0

    assert after == before + 1


def test_metrics_middleware_records_duration() -> None:
    """Verify request duration is recorded as a histogram observation."""
    from fastapi import FastAPI
    from prometheus_client import REGISTRY

    app = FastAPI()

    @app.get("/test-duration")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(MetricsMiddleware)

    with TestClient(app) as client:
        resp = client.get("/test-duration")
        assert resp.status_code == 200

    # The histogram should have at least one observation
    count = REGISTRY.get_sample_value(
        "ares_request_duration_seconds_count",
        {"method": "GET", "endpoint": "/test-duration"},
    ) or 0
    assert count >= 1


def test_metrics_middleware_records_error_status() -> None:
    """Verify 500 responses are recorded with status 500."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from prometheus_client import REGISTRY

    app = FastAPI()

    @app.get("/test-error")
    async def test_endpoint():
        return JSONResponse(status_code=500, content={"error": "internal"})

    app.add_middleware(MetricsMiddleware)

    with TestClient(app) as client:
        resp = client.get("/test-error")
        assert resp.status_code == 500

    count = REGISTRY.get_sample_value(
        "ares_requests_total",
        {"method": "GET", "endpoint": "/test-error", "status": "500"},
    ) or 0
    assert count >= 1


def test_make_metrics_app_returns_asgi_app() -> None:
    """Verify make_metrics_app returns a callable ASGI app."""
    from backend.core.metrics import make_metrics_app

    app = make_metrics_app()
    assert callable(app)


def test_record_agent_run() -> None:
    """Verify record_agent_run increments the counter."""
    from prometheus_client import REGISTRY

    from backend.core.metrics import record_agent_run

    before = REGISTRY.get_sample_value(
        "ares_agents_runs_total", {"agent": "test-agent", "status": "success"}
    ) or 0

    record_agent_run("test-agent", "success")

    after = REGISTRY.get_sample_value(
        "ares_agents_runs_total", {"agent": "test-agent", "status": "success"}
    ) or 0

    assert after == before + 1


def test_record_agent_fallback() -> None:
    """Verify record_agent_fallback increments the counter."""
    from prometheus_client import REGISTRY

    from backend.core.metrics import record_agent_fallback

    before = REGISTRY.get_sample_value(
        "ares_agents_fallback_total",
        {"agent": "test-agent", "from_model": "model-a", "to_model": "model-b"},
    ) or 0

    record_agent_fallback("test-agent", "model-a", "model-b")

    after = REGISTRY.get_sample_value(
        "ares_agents_fallback_total",
        {"agent": "test-agent", "from_model": "model-a", "to_model": "model-b"},
    ) or 0

    assert after == before + 1


def test_set_kill_switch_active() -> None:
    """Verify set_kill_switch_active sets the gauge."""
    from prometheus_client import REGISTRY

    from backend.core.metrics import set_kill_switch_active

    set_kill_switch_active(True)
    value = REGISTRY.get_sample_value("ares_live_kill_switch_active") or 0
    assert value == 1

    set_kill_switch_active(False)
    value = REGISTRY.get_sample_value("ares_live_kill_switch_active") or 0
    assert value == 0


def test_record_live_order() -> None:
    """Verify record_live_order increments the counter."""
    from prometheus_client import REGISTRY

    from backend.core.metrics import record_live_order

    before = REGISTRY.get_sample_value(
        "ares_live_orders_total", {"status": "filled"}
    ) or 0

    record_live_order("filled")

    after = REGISTRY.get_sample_value(
        "ares_live_orders_total", {"status": "filled"}
    ) or 0

    assert after == before + 1
