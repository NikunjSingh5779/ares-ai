"""Model router with fallback chain execution.

Implements the RELIABILITY section requirements:
- Primary → Fallback 1 → Fallback 2 → auto-router → graceful degradation
- Each step protected by circuit breaker and retry logic
- All failures logged with model id, error type, latency, fallback used
"""

from __future__ import annotations

import time
from typing import Any

from agents.circuit_breaker import CircuitBreakerRegistry, NoOpBreaker
from agents.client import LLMClient, NoOpLLMClient
from agents.queue import QueueRegistry
from agents.retry import RetryConfig, with_retry
from backend.core.exceptions import ModelUnavailableError


class RouterResult:
    """Result of a model router execution."""

    def __init__(self) -> None:
        self.success: bool = False
        self.response: dict[str, Any] | None = None
        self.model_used: str = ""
        self.attempts: int = 0
        self.total_latency_ms: int = 0
        self.fallback_used: bool = False
        self.degraded: bool = False
        self.errors: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "model_used": self.model_used,
            "attempts": self.attempts,
            "total_latency_ms": self.total_latency_ms,
            "fallback_used": self.fallback_used,
            "degraded": self.degraded,
            "errors": self.errors,
        }


class ModelRouter:
    """Executes a model call across a fallback chain.

    For each model in the chain:
    1. Check circuit breaker (fast-fail if OPEN)
    2. Acquire rate-limit slot
    3. Execute with retry logic (exponential backoff + jitter)
    4. On success → return result
    5. On failure → log error, try next model in chain
    6. If all models exhausted → graceful degradation
    """

    def __init__(
        self,
        llm_client: LLMClient | NoOpLLMClient,
        breaker_registry: CircuitBreakerRegistry,
        queue_registry: QueueRegistry,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self.client = llm_client
        self.breakers = breaker_registry
        self.queues = queue_registry
        self.retry_config = retry_config or RetryConfig()

    async def execute(
        self,
        model_chain: list[str],
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        rpm: int = 20,
    ) -> RouterResult:
        """Execute across the fallback chain.

        Args:
            model_chain: Ordered list of model IDs. First is primary.
            messages: Chat messages to send.
            temperature: Sampling temperature.
            max_tokens: Max tokens in response.
            rpm: Rate limit for each model.

        Returns:
            RouterResult with success/failure, response, model used, etc.
        """
        result = RouterResult()
        start = time.monotonic()

        for i, model_id in enumerate(model_chain):
            is_fallback = i > 0
            attempt_info: dict[str, Any] = {
                "model": model_id,
                "fallback": is_fallback,
                "error": None,
                "error_type": None,
                "latency_ms": 0,
            }
            model_start = time.monotonic()

            try:
                # Get or create circuit breaker for this model
                breaker = self.breakers.get(model_id)

                # Get or create rate-limit queue
                queue = self.queues.get(model_id, rpm=rpm)

                # Check circuit breaker first
                if not breaker.check():
                    attempt_info["error"] = f"Circuit breaker OPEN ({breaker.failure_count} consecutive failures)"
                    attempt_info["error_type"] = "circuit_breaker_open"
                    attempt_info["latency_ms"] = int((time.monotonic() - model_start) * 1000)
                    result.errors.append(attempt_info)
                    continue  # Try next model

                # Acquire rate-limit slot
                try:
                    wait_time = await queue.acquire()
                except RuntimeError as e:
                    attempt_info["error"] = str(e)
                    attempt_info["error_type"] = "queue_full"
                    attempt_info["latency_ms"] = int((time.monotonic() - model_start) * 1000)
                    result.errors.append(attempt_info)
                    continue

                try:
                    # Execute with retry
                    retry_result = await with_retry(
                        func=lambda: self.client.chat_completion(
                            model=model_id,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        ),
                        config=self.retry_config,
                        breaker=breaker,
                    )
                finally:
                    await queue.release()

                attempt_info["latency_ms"] = int((time.monotonic() - model_start) * 1000)

                if retry_result.success:
                    elapsed = int((time.monotonic() - start) * 1000)
                    result.success = True
                    result.response = retry_result.result
                    result.model_used = model_id
                    result.attempts = retry_result.attempts
                    result.total_latency_ms = elapsed
                    result.fallback_used = is_fallback
                    return result
                else:
                    attempt_info["error"] = str(retry_result.error)
                    attempt_info["error_type"] = retry_result.last_error_type
                    result.errors.append(attempt_info)
                    # Continue to next model in chain

            except Exception as e:
                attempt_info["error"] = str(e)
                attempt_info["error_type"] = type(e).__name__
                attempt_info["latency_ms"] = int((time.monotonic() - model_start) * 1000)
                result.errors.append(attempt_info)
                continue

        # All models exhausted — graceful degradation
        elapsed = int((time.monotonic() - start) * 1000)
        result.total_latency_ms = elapsed
        result.degraded = True
        result.response = {
            "error": True,
            "error_type": "all_models_exhausted",
            "model": model_chain[-1] if model_chain else "none",
            "choices": [],
            "usage": {"total_tokens": 0},
        }
        return result
