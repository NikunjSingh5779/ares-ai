"""Model router with fallback chain execution.

Implements the RELIABILITY section requirements:
- Primary → Fallback 1 → Fallback 2 → auto-router → graceful degradation
- Each step protected by circuit breaker and retry logic
- All failures logged with model id, error type, latency, fallback used
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agents.circuit_breaker import CircuitBreakerRegistry
from agents.client import LLMClient, NoOpLLMClient
from agents.queue import QueueRegistry
from agents.retry import RetryConfig, with_retry

logger = logging.getLogger(__name__)


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
        # Number of corrective (schema-violation) retries issued to the SAME
        # model — item 11 requires this to be auditable/logged.
        self.schema_corrections: int = 0
        # When a ``schema_type`` is supplied, the validated Pydantic object (or
        # None) goes here; ``response`` still holds the raw provider payload.
        self.parsed: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "model_used": self.model_used,
            "attempts": self.attempts,
            "total_latency_ms": self.total_latency_ms,
            "fallback_used": self.fallback_used,
            "degraded": self.degraded,
            "schema_corrections": self.schema_corrections,
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
        schema_type: type[Any] | None = None,
        breaker_threshold: int = 3,
        breaker_reset_seconds: float = 300.0,
    ) -> RouterResult:
        """Execute across the fallback chain.

        Args:
            model_chain: Ordered list of model IDs. First is primary.
            messages: Chat messages to send.
            temperature: Sampling temperature.
            max_tokens: Max tokens in response.
            rpm: Rate limit for each model.
            schema_type: Optional Pydantic model used for JSON Schema structured
                output. When provided, a single corrective (JSON-only) retry is
                issued to the SAME model on an invalid parse, then the next
                fallback is used.
            breaker_threshold: per-model consecutive-failure threshold (honours
                ``configs/models.yaml`` ``circuit_breaker_threshold``).
            breaker_reset_seconds: breaker reset window (honours
                ``circuit_breaker_reset_seconds``).

        Returns:
            RouterResult with success/failure, response, model used, etc.
        """
        result = RouterResult()
        start = time.monotonic()
        json_schema = schema_type.model_json_schema() if schema_type is not None else None
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
                # Get or create circuit breaker honouring per-model limits.
                breaker = self.breakers.get_or_register(model_id, breaker_threshold, breaker_reset_seconds)
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
                    queue_wait = await queue.acquire()
                    attempt_info["queue_wait_ms"] = int(queue_wait * 1000)
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
                            json_schema=json_schema,
                        ),
                        config=self.retry_config,
                        breaker=breaker,
                    )
                finally:
                    await queue.release()
                attempt_info["latency_ms"] = int((time.monotonic() - model_start) * 1000)
                if retry_result.success:
                    parsed_out: Any = None
                    if schema_type is not None:
                        content = self._extract_content(retry_result.result or {})
                        parsed_out = self._validate_content(content, schema_type)
                        if parsed_out is None:
                            # One corrective JSON-only retry to the SAME model.
                            result.schema_corrections += 1
                            corrective_messages = [
                                *messages,
                                {
                                    "role": "system",
                                    "content": (
                                        "Your previous output did not conform to the required JSON schema. "
                                        "Correct it and return ONLY valid JSON matching the schema."
                                    ),
                                },
                            ]
                            try:
                                corr_resp = await self.client.chat_completion(
                                    model=model_id,
                                    messages=corrective_messages,
                                    temperature=temperature,
                                    max_tokens=max_tokens,
                                    json_schema=json_schema,
                                )
                                parsed_out = self._validate_content(self._extract_content(corr_resp), schema_type)
                            except Exception as exc:  # noqa: BLE001 - fail to next fallback
                                logger.error("Corrective retry failed for %s: %s", model_id, exc)
                                parsed_out = None
                            if parsed_out is None:
                                attempt_info["error"] = "Invalid JSON/schema output after one corrective retry"
                                attempt_info["error_type"] = "schema_error"
                                attempt_info["latency_ms"] = int((time.monotonic() - model_start) * 1000)
                                result.errors.append(attempt_info)
                                continue  # Try next model
                    elapsed = int((time.monotonic() - start) * 1000)
                    result.success = True
                    result.response = retry_result.result
                    result.parsed = parsed_out
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
                logger.error(f"Unhandled exception: {e}", exc_info=True)
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

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str | None:
        """Extract the text content from an OpenAI-style chat payload."""
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

    @staticmethod
    def _validate_content(content: str | None, schema_type: type[Any]) -> Any | None:
        """Validate raw JSON text against a Pydantic model (JSON Schema)."""
        if not content:
            return None
        try:
            return schema_type.model_validate_json(content)  # type: ignore[union-attr]
        except Exception:
            return None
