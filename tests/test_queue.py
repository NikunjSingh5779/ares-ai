"""Tests for per-model request queue (rate-limit compliance)."""
from __future__ import annotations

import asyncio

import pytest

from agents.queue import ModelRequestQueue, QueueRegistry


class TestModelRequestQueue:
    @pytest.mark.asyncio
    async def test_acquire_under_limit(self) -> None:
        queue = ModelRequestQueue(model_id="test", rpm=10)
        wait = await queue.acquire()
        assert wait == 0.0  # immediate
        assert queue.active_count == 1
        assert queue.pending_count == 0  # already released

    @pytest.mark.asyncio
    async def test_acquire_multiple_under_limit(self) -> None:
        queue = ModelRequestQueue(model_id="test", rpm=10)
        for _ in range(5):
            wait = await queue.acquire()
            assert wait == 0.0
        assert queue.active_count == 5

    @pytest.mark.asyncio
    async def test_blocks_when_at_limit(self) -> None:
        queue = ModelRequestQueue(model_id="test", rpm=1, max_queued=10)

        wait1 = await queue.acquire()
        assert wait1 == 0.0

        # Second acquire should block (1 RPM = 1 per 60s window)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.acquire(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_raises_when_queue_full(self) -> None:
        """max_queued exceeded raises RuntimeError."""
        queue = ModelRequestQueue(model_id="test", rpm=100, max_queued=2)
        # Simulate many concurrent waiters by setting _pending directly
        queue._pending = 5
        with pytest.raises(RuntimeError, match="Queue full"):
            await queue.acquire()

    @pytest.mark.asyncio
    async def test_sliding_window_expires_old_entries(self) -> None:
        """Old entries should be removed from the window."""
        queue = ModelRequestQueue(model_id="test", rpm=2)

        # Add two entries with manual timestamps in the past
        import time
        past = time.monotonic() - 120  # 120 seconds ago
        queue._slots = [past, past]

        assert queue.active_count == 0  # Both expired

    @pytest.mark.asyncio
    async def test_release_is_noop(self) -> None:
        queue = ModelRequestQueue(model_id="test", rpm=10)
        wait = await queue.acquire()
        assert wait == 0.0
        await queue.release()  # Should not raise
        assert queue.active_count == 1  # Still tracked in window

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        queue = ModelRequestQueue(model_id="test-model", rpm=15, max_queued=100)
        await queue.acquire()
        stats = queue.stats()

        assert stats["model_id"] == "test-model"
        assert stats["rpm_limit"] == 15
        assert stats["active_in_window"] == 1
        assert stats["max_queued"] == 100

    @pytest.mark.asyncio
    async def test_high_rpm_capacity(self) -> None:
        """With RPM=50, we should be able to acquire 10 times immediately."""
        queue = ModelRequestQueue(model_id="test", rpm=50)
        for _ in range(10):
            wait = await queue.acquire()
            assert wait == 0.0
        assert queue.active_count == 10


class TestQueueRegistry:
    def test_get_creates_new(self) -> None:
        registry = QueueRegistry()
        queue = registry.get("model-a")
        assert queue.model_id == "model-a"
        assert queue.rpm == 20

    def test_get_returns_same(self) -> None:
        registry = QueueRegistry()
        q1 = registry.get("model-a")
        q2 = registry.get("model-a")
        assert q1 is q2

    def test_register_with_custom_rpm(self) -> None:
        registry = QueueRegistry()
        queue = registry.register("model-a", rpm=100)
        assert queue.rpm == 100

    def test_get_with_custom_rpm_for_new(self) -> None:
        registry = QueueRegistry()
        queue = registry.get("model-a", rpm=50)
        assert queue.rpm == 50

    def test_get_ignores_rpm_for_existing(self) -> None:
        """If queue already exists, rpm parameter is ignored."""
        registry = QueueRegistry()
        registry.register("model-a", rpm=10)
        queue = registry.get("model-a", rpm=999)
        assert queue.rpm == 10  # unchanged

    def test_all_stats(self) -> None:
        registry = QueueRegistry()
        registry.get("model-a")
        registry.get("model-b", rpm=5)
        stats = registry.all_stats()
        assert "model-a" in stats
        assert "model-b" in stats
        assert stats["model-b"]["rpm_limit"] == 5
