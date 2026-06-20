#!/usr/bin/env python3
"""
ARES AI — Load test script (locust-based).

Usage:
    pip install locust
    locust -f scripts/load-test.py --host=http://localhost:8000

Test scenarios:
    - /health (unauthenticated)
    - /api/v1/analyze (analysis pipeline)
    - /api/v1/signal (trading signal)

Designed for CI/CD pipeline integration:
    locust -f scripts/load-test.py --host=http://localhost:8000 \\
        --headless -u 10 -r 2 --run-time 30s \\
        --csv=results/load-test
"""

from __future__ import annotations

import random

from locust import FastHttpUser, between, task


class HealthUser(FastHttpUser):
    """Lightweight health-check user (no auth needed)."""

    wait_time = between(0.5, 2.0)

    @task(10)
    def health_check(self) -> None:
        self.client.get("/health", name="/health")


class AnalysisUser(FastHttpUser):
    """Simulates analysis pipeline requests."""

    wait_time = between(2.0, 5.0)

    SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "ADA-USD"]

    def on_start(self) -> None:
        """Set up API key from environment."""
        self.api_key = "changeme_in_production"

    @task(5)
    def analyze(self) -> None:
        symbol = random.choice(self.SYMBOLS)
        with self.client.post(
            "/api/v1/analyze",
            json={"symbol": symbol, "request": f"Analyze {symbol}"},
            headers={"X-API-Key": self.api_key},
            name="/api/v1/analyze",
            catch_response=True,
        ) as resp:
            if resp.status_code == 429:
                resp.success()  # Rate-limited responses are expected
            elif resp.status_code >= 500:
                resp.failure(f"Server error: {resp.status_code}")

    @task(3)
    def signal(self) -> None:
        symbol = random.choice(self.SYMBOLS)
        with self.client.post(
            "/api/v1/signal",
            json={"symbol": symbol, "request": f"Signal for {symbol}"},
            headers={"X-API-Key": self.api_key},
            name="/api/v1/signal",
            catch_response=True,
        ) as resp:
            if resp.status_code == 429:
                resp.success()
            elif resp.status_code >= 500:
                resp.failure(f"Server error: {resp.status_code}")

    @task(1)
    def portfolio(self) -> None:
        with self.client.get(
            "/api/v1/portfolio",
            headers={"X-API-Key": self.api_key},
            name="/api/v1/portfolio",
        ) as resp:
            if resp.status_code == 429:
                resp.success()


class MixedUser(FastHttpUser):
    """Mixed workload — health + authenticated calls."""

    wait_time = between(1.0, 3.0)

    def on_start(self) -> None:
        self.api_key = "changeme_in_production"

    @task(3)
    def health(self) -> None:
        self.client.get("/health", name="/health")

    @task(2)
    def agent_status(self) -> None:
        self.client.get(
            "/api/v1/agents/status",
            headers={"X-API-Key": self.api_key},
            name="/api/v1/agents/status",
        )

    @task(1)
    def live_status(self) -> None:
        self.client.get(
            "/api/v1/live/status",
            headers={"X-API-Key": self.api_key},
            name="/api/v1/live/status",
        )
