"""Retry logic with exponential backoff and jitter.

Implements the RELIABILITY section requirements:
- Exponential backoff with jitter on transient errors
- Capped retry count (default 3) before moving to next fallback
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Awaitable, Callable, TypeVar

from backend.core.exceptions import ModelUnavailableError

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter_factor: float = 0.1,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter_factor = jitter_factor

    def delay(self, attempt: int) -> float:
        """Calculate delay for attempt number (0-indexed).

        delay = min(base * 2^attempt, max_delay) + jitter
        """
        exponential = min(self.base_delay * (2 ** attempt), self.max_delay)
        jitter = random.uniform(0, exponential * self.jitter_factor)
        return exponential + jitter

    def copy(self) -> RetryConfig:
        return RetryConfig(
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            jitter_factor=self.jitter_factor,
        )


# Common retryable HTTP status codes
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Common retryable exception types
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)


def is_retryable_error(exception: Exception) -> bool:
    """Check if an exception should trigger a retry."""
    if isinstance(exception, RETRYABLE_EXCEPTIONS):
        return True
    # httpx-specific
    if type(exception).__name__ in ("HTTPStatusError", "HTTPError", "ConnectError", "RemoteProtocolError"):
        return True
    # Check for status code in HTTPStatusError
    if hasattr(exception, "response") and hasattr(exception.response, "status_code"):
        return exception.response.status_code in RETRYABLE_STATUSES
    return False


class RetryResult:
    """Result of a retry operation."""

    def __init__(self) -> None:
        self.success: bool = False
        self.result: T | None = None  # type: ignore[valid-type]
        self.error: Exception | None = None
        self.attempts: int = 0
        self.total_delay_ms: int = 0
        self.last_error_type: str = ""


async def with_retry(
    func: Callable[[], Awaitable[T]],
    config: RetryConfig | None = None,
    breaker: Any | None = None,  # ModelCircuitBreaker or NoOpBreaker
) -> RetryResult:
    """Execute a callable with retry logic.

    1. Check circuit breaker first (fast-fail if OPEN)
    2. Execute the function
    3. On success, record success with breaker, return result
    4. On retryable error, wait with backoff+jitter, retry
    5. On non-retryable error, record failure, raise immediately
    6. After exhausting retries, record failure, return failure result

    Args:
        func: Async callable to execute.
        config: Retry configuration. Uses defaults if None.
        breaker: Circuit breaker for this model. NoOp if None.

    Returns:
        RetryResult with success/failure, result or error, attempt count.
    """
    cfg = config or RetryConfig()
    result = RetryResult()
    start = time.monotonic()

    last_error: Exception | None = None

    for attempt in range(cfg.max_retries + 1):
        result.attempts = attempt + 1

        # Check circuit breaker
        if breaker is not None and not breaker.check():
            result.success = False
            result.error = ModelUnavailableError(
                f"Circuit breaker OPEN for model. "
                f"Consecutive failures: {breaker.failure_count}"
            )
            result.last_error_type = "circuit_breaker_open"
            return result

        try:
            output = await func()
            elapsed_ms = int((time.monotonic() - start) * 1000)
            result.total_delay_ms = elapsed_ms
            result.success = True
            result.result = output
            if breaker is not None:
                breaker.record_success()
            return result

        except Exception as e:
            last_error = e
            result.last_error_type = type(e).__name__

            if attempt < cfg.max_retries and is_retryable_error(e):
                if breaker is not None:
                    breaker.record_failure()
                delay = cfg.delay(attempt)
                await asyncio.sleep(delay)
            else:
                # Non-retryable — fail immediately
                if breaker is not None:
                    breaker.record_failure()
                result.success = False
                result.error = last_error
                return result

    # All retries exhausted
    elapsed_ms = int((time.monotonic() - start) * 1000)
    result.total_delay_ms = elapsed_ms
    result.success = False
    result.error = last_error
    return result
