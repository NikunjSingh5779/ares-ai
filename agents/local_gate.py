"""Process-wide concurrency gate for the single-request local model.

The local model is expected to serve one generation at a time; the gate defaults
to one concurrent request. A per-router queue is not enough because chat and
analysis can each hold their own router; this gate is a process-wide semaphore
instead. Acquisition is bounded so a second request fails closed rather than
waiting forever.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("ares.local_llm")

LOCAL_MODEL_PREFIX = "local/"


class LocalModelBusyError(RuntimeError):
    """No local-model slot opened before the configured queue timeout."""


def is_local_model(model_id: str) -> bool:
    """Return whether a roster ID routes to the local OpenAI-compatible server."""
    return model_id.startswith(LOCAL_MODEL_PREFIX)


class LocalModelGate:
    """Bounded async semaphore shared by every router in this process."""

    def __init__(self, max_concurrent: int = 1, queue_timeout_seconds: float = 20.0) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        if queue_timeout_seconds <= 0:
            raise ValueError("queue_timeout_seconds must be positive")
        self.max_concurrent = max_concurrent
        self.queue_timeout_seconds = queue_timeout_seconds
        self._semaphore: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._in_use = 0

    def _semaphore_for_current_loop(self) -> asyncio.Semaphore:
        """Create a semaphore per event loop (tests use a loop per test)."""
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._loop is not loop:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
            self._loop = loop
            self._in_use = 0
        return self._semaphore

    async def acquire(self) -> None:
        """Acquire one local slot or raise :class:`LocalModelBusyError`."""
        semaphore = self._semaphore_for_current_loop()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self.queue_timeout_seconds)
        except TimeoutError as exc:
            logger.warning(
                "Local model gate timed out after %.1fs (max_concurrent=%d)",
                self.queue_timeout_seconds,
                self.max_concurrent,
            )
            raise LocalModelBusyError(
                f"Local model is busy; no slot opened within {self.queue_timeout_seconds:.1f}s"
            ) from exc
        self._in_use += 1

    def release(self) -> None:
        """Release a previously acquired slot."""
        if self._semaphore is None or self._in_use <= 0:
            raise RuntimeError("Local model gate released without a matching acquire")
        self._in_use -= 1
        self._semaphore.release()

    @property
    def in_use(self) -> int:
        """Number of slots currently held (process-local diagnostic)."""
        return self._in_use


_gate: LocalModelGate | None = None
_gate_config: tuple[int, float] | None = None


def get_local_model_gate() -> LocalModelGate:
    """Return the process-wide gate, rebuilding it if settings changed."""
    global _gate, _gate_config  # noqa: PLW0603
    from backend.core.config import settings

    config = (settings.local_llm_max_concurrent, settings.local_llm_queue_timeout_seconds)
    if _gate is None or _gate_config != config:
        _gate = LocalModelGate(*config)
        _gate_config = config
    return _gate


def reset_local_model_gate() -> None:
    """Drop the cached gate (tests and configuration reloads)."""
    global _gate, _gate_config  # noqa: PLW0603
    _gate = None
    _gate_config = None
