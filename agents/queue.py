"""Per-model request queue for rate-limit compliance.

Implements the RELIABILITY section requirements:
- Request queue per model to stay under per-minute limits
- Rather than bursting and getting throttled
"""

from __future__ import annotations

import asyncio
import time
from typing import Any


class ModelRequestQueue:
    """Per-model rate limiter using a sliding window approach.

    Queues requests to stay under a configurable per-minute limit.
    If the queue is full, acquire() blocks until a slot opens.
    """

    def __init__(
        self,
        model_id: str,
        rpm: int = 20,
        max_queued: int = 50,
    ) -> None:
        self.model_id = model_id
        self.rpm = rpm
        self.max_queued = max_queued

        self._slots: list[float] = []  # Timestamps of recent requests
        self._pending: int = 0
        self._lock = asyncio.Lock()
        self._last_request_time: float = 0.0

    async def acquire(self) -> float:
        """Wait for a rate-limit slot and return the wait time.

        Blocks until a slot is available within the RPM limit.
        If max_queued is exceeded, raises RuntimeError.
        """
        if self._pending > self.max_queued:
            raise RuntimeError(
                f"Queue full for model '{self.model_id}': "
                f"{self._pending} pending > {self.max_queued} max"
            )

        self._pending += 1
        try:
            wait = await self._wait_for_slot()
            return wait
        finally:
            self._pending -= 1

    async def _wait_for_slot(self) -> float:
        """Wait until a slot is available. Returns wait time in seconds."""
        async with self._lock:
            now = time.monotonic()
            
            # Enforce minimal stagger to prevent API burst limit 429s
            time_since_last = now - self._last_request_time
            if time_since_last < 0.25:
                stagger_wait = 0.25 - time_since_last
                await asyncio.sleep(stagger_wait)
                now = time.monotonic()
            
            # Remove timestamps older than 60 seconds
            window_start = now - 60.0
            self._slots = [t for t in self._slots if t > window_start]

            # If we're under the limit, permit immediately
            if len(self._slots) < self.rpm:
                self._slots.append(now)
                self._last_request_time = now
                return 0.0

            # Need to wait — oldest slot expires in `oldest + 60 - now` seconds
            oldest = min(self._slots)
            wait_time = oldest + 60.0 - now
            if wait_time > 0:
                await asyncio.sleep(wait_time)

            # After waiting, add a new slot
            new_now = time.monotonic()
            self._slots.append(new_now)
            self._last_request_time = new_now
            return wait_time

    async def release(self) -> None:
        """Release a slot. Not strictly needed with sliding window,
        but kept for API compatibility with semaphore-based rate limiters."""
        pass

    @property
    def active_count(self) -> int:
        """Number of requests in the current 60-second window."""
        now = time.monotonic()
        window_start = now - 60.0
        return len([t for t in self._slots if t > window_start])

    @property
    def pending_count(self) -> int:
        """Number of requests waiting for a slot."""
        return self._pending

    def stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        return {
            "model_id": self.model_id,
            "rpm_limit": self.rpm,
            "active_in_window": self.active_count,
            "pending": self._pending,
            "max_queued": self.max_queued,
        }


class QueueRegistry:
    """Manages request queues for all models."""

    def __init__(self) -> None:
        self._queues: dict[str, ModelRequestQueue] = {}

    def get(self, model_id: str, rpm: int = 20) -> ModelRequestQueue:
        """Get or create a queue for a model."""
        if model_id not in self._queues:
            self._queues[model_id] = ModelRequestQueue(model_id=model_id, rpm=rpm)
        return self._queues[model_id]

    def register(self, model_id: str, rpm: int) -> ModelRequestQueue:
        """Register a queue with a specific RPM."""
        queue = ModelRequestQueue(model_id=model_id, rpm=rpm)
        self._queues[model_id] = queue
        return queue

    def all_stats(self) -> dict[str, dict[str, Any]]:
        """Get stats for all queues."""
        return {mid: q.stats() for mid, q in self._queues.items()}
