"""Tests for retry logic with exponential backoff and jitter."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from agents.retry import (
    RetryConfig,
    RetryResult,
    is_retryable_error,
    with_retry,
)


class TestRetryConfig:
    def test_default_values(self) -> None:
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 60.0
        assert cfg.jitter_factor == 0.1

    def test_delay_exponential(self) -> None:
        cfg = RetryConfig(base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        assert cfg.delay(0) == 1.0     # 1 * 2^0 = 1
        assert cfg.delay(1) == 2.0     # 1 * 2^1 = 2
        assert cfg.delay(2) == 4.0     # 1 * 2^2 = 4
        assert cfg.delay(3) == 8.0     # 1 * 2^3 = 8

    def test_delay_capped_at_max(self) -> None:
        cfg = RetryConfig(base_delay=10.0, max_delay=30.0, jitter_factor=0.0)
        assert cfg.delay(0) == 10.0
        assert cfg.delay(1) == 20.0
        assert cfg.delay(2) == 30.0  # 10 * 2^2 = 40, capped at 30
        assert cfg.delay(5) == 30.0  # capped

    def test_delay_with_jitter(self) -> None:
        cfg = RetryConfig(base_delay=1.0, max_delay=60.0, jitter_factor=0.5)
        d = cfg.delay(0)
        assert 1.0 <= d <= 1.5  # 1.0 + up to 0.5 jitter

    def test_delay_jitter_scales_with_exponential(self) -> None:
        cfg = RetryConfig(base_delay=1.0, max_delay=60.0, jitter_factor=0.1)
        d2 = cfg.delay(2)
        assert 4.0 <= d2 <= 4.4  # 4.0 + up to 0.4 jitter

    def test_copy_is_independent(self) -> None:
        cfg = RetryConfig(max_retries=5, base_delay=2.0)
        copied = cfg.copy()
        assert copied.max_retries == 5
        assert copied.base_delay == 2.0
        copied.max_retries = 3
        assert cfg.max_retries == 5  # original unchanged


class TestRetryableErrorDetection:
    def test_connection_error(self) -> None:
        assert is_retryable_error(ConnectionError("connection refused"))

    def test_timeout_error(self) -> None:
        assert is_retryable_error(TimeoutError("timed out"))

    def test_asyncio_timeout(self) -> None:
        assert is_retryable_error(asyncio.TimeoutError())

    def test_retryable_http_status(self) -> None:
        """429, 500, 502, 503, 504 are retryable."""
        for code in [429, 500, 502, 503, 504]:
            err = _make_http_error(code)
            assert is_retryable_error(err), f"Status {code} should be retryable"

    def test_non_retryable_http_status(self) -> None:
        """400, 401, 403, 404 are not retryable."""
        for code in [400, 401, 403, 404]:
            err = _make_http_error(code)
            assert not is_retryable_error(err), f"Status {code} should not be retryable"

    def test_value_error_not_retryable(self) -> None:
        assert not is_retryable_error(ValueError("bad value"))

    def test_key_error_not_retryable(self) -> None:
        assert not is_retryable_error(KeyError("missing key"))


class _MockHTTPError(Exception):
    """Mock of httpx.HTTPStatusError for testing."""

    def __init__(self, status_code: int) -> None:
        self.response = _MockResponse(status_code)
        super().__init__(f"HTTP error {status_code}")


class _MockResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _make_http_error(code: int) -> Exception:
    return _MockHTTPError(code)


class TestWithRetry:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self) -> None:
        func = AsyncMock(return_value="success")
        result = await with_retry(func)

        assert result.success is True
        assert result.result == "success"
        assert result.attempts == 1
        assert result.error is None
        assert result.last_error_type == ""
        func.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self) -> None:
        """Fail twice, succeed on third attempt."""
        call_count = 0

        async def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("temporary failure")
            return "success"

        result = await with_retry(flaky_func, config=RetryConfig(max_retries=4, base_delay=0.01))

        assert result.success is True
        assert result.result == "success"
        assert result.attempts == 3  # 2 failures + 1 success

    @pytest.mark.asyncio
    async def test_exhaust_retries(self) -> None:
        """Always fails → all retries exhausted."""
        func = AsyncMock(side_effect=ConnectionError("persistent failure"))

        result = await with_retry(func, config=RetryConfig(max_retries=2, base_delay=0.01))

        assert result.success is False
        assert result.attempts == 3  # initial + 2 retries = 3 attempts
        assert result.error is not None
        assert "persistent failure" in str(result.error)
        assert result.last_error_type == "ConnectionError"

    @pytest.mark.asyncio
    async def test_non_retryable_error_immediate_fail(self) -> None:
        func = AsyncMock(side_effect=ValueError("bad input"))

        result = await with_retry(func, config=RetryConfig(max_retries=3, base_delay=0.01))

        assert result.success is False
        assert result.attempts == 1  # no retries for non-retryable
        assert result.last_error_type == "ValueError"
        func.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_fast_fail(self) -> None:
        """If breaker.check() returns False, fail immediately."""
        from agents.circuit_breaker import ModelCircuitBreaker

        breaker = ModelCircuitBreaker(model_id="test", consecutive_threshold=1)
        breaker.record_failure()  # trips breaker
        assert breaker.check() is False

        func = AsyncMock(return_value="should not run")

        result = await with_retry(func, breaker=breaker, config=RetryConfig(max_retries=2, base_delay=0.01))

        assert result.success is False
        assert result.last_error_type == "circuit_breaker_open"
        assert "Circuit breaker OPEN" in str(result.error)
        func.assert_not_awaited()  # function never called

    @pytest.mark.asyncio
    async def test_breaker_success_resets_counter(self) -> None:
        from agents.circuit_breaker import ModelCircuitBreaker

        breaker = ModelCircuitBreaker(model_id="test", consecutive_threshold=3)
        func = AsyncMock(return_value="ok")

        result = await with_retry(func, breaker=breaker)
        assert result.success is True
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_breaker_failure_records(self) -> None:
        from agents.circuit_breaker import ModelCircuitBreaker

        breaker = ModelCircuitBreaker(model_id="test", consecutive_threshold=3)
        func = AsyncMock(side_effect=ConnectionError("fail"))

        result = await with_retry(func, breaker=breaker, config=RetryConfig(max_retries=1, base_delay=0.01))
        assert result.success is False
        assert breaker.failure_count > 0

    def test_retry_result_defaults(self) -> None:
        result = RetryResult()
        assert result.success is False
        assert result.result is None
        assert result.error is None
        assert result.attempts == 0
        assert result.total_delay_ms == 0
        assert result.last_error_type == ""
