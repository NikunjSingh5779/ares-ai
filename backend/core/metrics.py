"""Prometheus metrics instrumentation.

Provides a ``MetricsMiddleware`` ASGI middleware that records:
- Request count, duration, and status per endpoint/method
- Agent run and fallback counters (called from agent orchestrator)
- Live trading metrics (kill switch, order count)

Usage in ``backend/main.py``::

    from backend.core.metrics import MetricsMiddleware
    app.add_middleware(MetricsMiddleware)
    app.mount("/metrics", make_metrics_app())
"""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, generate_latest, make_asgi_app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# ── HTTP request metrics ─────────────────────────────────────────────────────

REQUESTS_TOTAL = Counter(
    "ares_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_DURATION_SECONDS = Histogram(
    "ares_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ── Agent metrics ───────────────────────────────────────────────────────────

AGENTS_RUNS_TOTAL = Counter(
    "ares_agents_runs_total",
    "Total agent runs",
    ["agent", "status"],
)

AGENTS_FALLBACK_TOTAL = Counter(
    "ares_agents_fallback_total",
    "Agent model fallback events",
    ["agent", "from_model", "to_model"],
)

# ── Live trading metrics ────────────────────────────────────────────────────

LIVE_KILL_SWITCH_ACTIVE = Gauge(
    "ares_live_kill_switch_active",
    "Whether the live trading kill switch is active (1) or not (0)",
)

LIVE_ORDERS_TOTAL = Counter(
    "ares_live_orders_total",
    "Total live orders placed",
    ["status"],
)


# ── ASGI middleware ─────────────────────────────────────────────────────────


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count, duration, and status for every HTTP request."""

    async def dispatch(self, request: Request, call_next: callable) -> Response:  # type: ignore[type-arg]
        method = request.method
        endpoint = request.url.path

        start = time.monotonic()
        try:
            response = await call_next(request)
            status = str(response.status_code)
            REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=status).inc()
            return response
        except Exception as exc:
            REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status="500").inc()
            raise
        finally:
            duration = time.monotonic() - start
            REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)


# ── Public helpers ──────────────────────────────────────────────────────────


def make_metrics_app():
    """Return an ASGI app that serves ``/metrics`` in Prometheus format.

    Usage::

        from backend.core.metrics import make_metrics_app
        app.mount("/metrics", make_metrics_app())
    """
    return make_asgi_app()


def record_agent_run(agent: str, status: str) -> None:
    """Increment the agent runs counter."""
    AGENTS_RUNS_TOTAL.labels(agent=agent, status=status).inc()


def record_agent_fallback(agent: str, from_model: str, to_model: str) -> None:
    """Increment the agent fallback counter."""
    AGENTS_FALLBACK_TOTAL.labels(agent=agent, from_model=from_model, to_model=to_model).inc()


def set_kill_switch_active(active: bool) -> None:
    """Set the kill switch gauge (1 = active, 0 = inactive)."""
    LIVE_KILL_SWITCH_ACTIVE.set(1 if active else 0)


def record_live_order(status: str) -> None:
    """Increment the live order counter."""
    LIVE_ORDERS_TOTAL.labels(status=status).inc()
