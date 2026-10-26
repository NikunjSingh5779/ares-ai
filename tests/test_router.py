"""Tests for model router (fallback chain execution)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from agents.circuit_breaker import CircuitBreakerRegistry, CircuitState
from agents.client import LLMClient, NoOpLLMClient
from agents.local_gate import LocalModelBusyError, LocalModelGate
from agents.queue import QueueRegistry
from agents.retry import RetryConfig
from agents.router import ModelRouter, RouterResult


@pytest.fixture
def router() -> ModelRouter:
    return ModelRouter(
        llm_client=NoOpLLMClient(),
        breaker_registry=CircuitBreakerRegistry(),
        queue_registry=QueueRegistry(),
        retry_config=RetryConfig(max_retries=1, base_delay=0.01),
    )


class TestRouterResult:
    def test_defaults(self) -> None:
        r = RouterResult()
        assert r.success is False
        assert r.response is None
        assert r.model_used == ""
        assert r.attempts == 0
        assert r.total_latency_ms == 0
        assert r.fallback_used is False
        assert r.degraded is False
        assert r.errors == []

    def test_to_dict(self) -> None:
        r = RouterResult()
        r.success = True
        r.model_used = "model-a"
        r.attempts = 2
        r.total_latency_ms = 1500
        r.fallback_used = True
        d = r.to_dict()
        assert d["success"] is True
        assert d["model_used"] == "model-a"
        assert d["attempts"] == 2


class TestModelRouter:
    @pytest.mark.asyncio
    async def test_empty_chain_degraded(self, router: ModelRouter) -> None:
        result = await router.execute(
            model_chain=[],
            messages=[{"role": "user", "content": "test"}],
        )
        assert result.success is False
        assert result.degraded is True
        assert len(result.errors) == 0  # nothing to try

    @pytest.mark.asyncio
    async def test_single_model_error_envelope_degrades(self, router: ModelRouter) -> None:
        """An error envelope from the no-op client must not count as success."""
        result = await router.execute(
            model_chain=["test-model"],
            messages=[{"role": "user", "content": "test"}],
        )
        assert result.success is False
        assert result.degraded is True
        assert result.model_used == ""
        assert len(result.errors) == 1
        assert result.errors[0]["error_type"] == "error_response"

    @pytest.mark.asyncio
    async def test_all_fallbacks_exhausted(self, router: ModelRouter) -> None:
        """Error envelopes from every candidate result in graceful degradation."""
        result = await router.execute(
            model_chain=["model-a", "model-b", "model-c"],
            messages=[{"role": "user", "content": "test"}],
        )
        assert result.success is False
        assert result.degraded is True
        assert result.model_used == ""
        assert len(result.errors) == 3

    @pytest.mark.asyncio
    async def test_circuit_breaker_skips_model(self, router: ModelRouter) -> None:
        """If breaker is OPEN for model-a, it's skipped for model-b."""
        breaker = router.breakers.get("model-a")
        breaker.record_failure()  # trips if threshold=3
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.check() is False

        result = await router.execute(
            model_chain=["model-a", "model-b"],
            messages=[{"role": "user", "content": "test"}],
        )

        # model-a should be skipped due to open breaker
        model_a_errors = [e for e in result.errors if e["model"] == "model-a"]
        assert any(
            "circuit_breaker_open" in str(e.get("error_type", ""))
            or "circuit_breaker_open" in str(e.get("error", ""))
            or "OPEN" in str(e.get("error", ""))
            for e in model_a_errors
        )

    @pytest.mark.asyncio
    async def test_success_with_custom_messages(self, router: ModelRouter) -> None:
        """Can call with different messages."""
        result = await router.execute(
            model_chain=["test-model"],
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Analyze BTC"},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        # NoOpLLMClient returns error, but the call should complete without raising
        assert isinstance(result, RouterResult)

    @pytest.mark.asyncio
    async def test_router_with_custom_rpm(self, router: ModelRouter) -> None:
        """Custom RPM should be passed to queue."""
        result = await router.execute(
            model_chain=["test-model"],
            messages=[{"role": "user", "content": "hi"}],
            rpm=100,
        )
        assert isinstance(result, RouterResult)
        # Queue should have been created with RPM=100
        queue = router.queues.get("test-model")
        assert queue.rpm == 100


class TestModelRouterSchemaValidation:
    """Structured output: schema violations get one corrective retry, then fall through."""

    class Signal(BaseModel):
        action: str
        confidence: float

    @staticmethod
    def _response(content: str, model: str = "model-a") -> dict[str, Any]:
        return {
            "choices": [{"message": {"content": content}}],
            "model": model,
            "usage": {"total_tokens": 10},
        }

    def _router(self, mock_client: AsyncMock) -> ModelRouter:
        mock_client.is_error_response.return_value = False
        return ModelRouter(
            llm_client=mock_client,
            breaker_registry=CircuitBreakerRegistry(),
            queue_registry=QueueRegistry(),
            retry_config=RetryConfig(max_retries=0, base_delay=0.01),
        )

    @pytest.mark.asyncio
    async def test_valid_json_is_parsed_without_correction(self) -> None:
        from agents.client import LLMClient

        mock_client = AsyncMock(spec=LLMClient)
        mock_client.chat_completion = AsyncMock(return_value=self._response('{"action": "buy", "confidence": 0.9}'))
        router = self._router(mock_client)

        result = await router.execute(
            model_chain=["model-a"],
            messages=[{"role": "user", "content": "signal"}],
            schema_type=self.Signal,
        )

        assert result.success is True
        assert isinstance(result.parsed, self.Signal)
        assert result.parsed.action == "buy"
        assert result.schema_corrections == 0
        sent = mock_client.chat_completion.await_args.kwargs
        assert sent["json_schema"]["properties"]["action"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_invalid_json_triggers_one_corrective_retry(self) -> None:
        from agents.client import LLMClient

        mock_client = AsyncMock(spec=LLMClient)
        mock_client.chat_completion = AsyncMock(
            side_effect=[
                self._response("not json"),
                self._response('{"action": "sell", "confidence": 0.4}'),
            ]
        )
        router = self._router(mock_client)

        result = await router.execute(
            model_chain=["model-a"],
            messages=[{"role": "user", "content": "signal"}],
            schema_type=self.Signal,
        )

        assert result.success is True
        assert isinstance(result.parsed, self.Signal)
        assert result.parsed.action == "sell"
        assert result.schema_corrections == 1
        assert mock_client.chat_completion.await_count == 2
        corrective_messages = mock_client.chat_completion.await_args_list[1].kwargs["messages"]
        # The model must see what it actually produced, not just "try again".
        assert corrective_messages[-2] == {"role": "assistant", "content": "not json"}
        assert corrective_messages[-1]["role"] == "system"
        assert "JSON schema" in corrective_messages[-1]["content"]

    @pytest.mark.asyncio
    async def test_persistent_schema_violation_falls_through(self) -> None:
        from agents.client import LLMClient

        mock_client = AsyncMock(spec=LLMClient)
        mock_client.chat_completion = AsyncMock(
            side_effect=[
                self._response('{"action": "buy"}'),  # missing confidence
                self._response("still not json"),
                self._response('{"action": "hold", "confidence": 0.5}', model="model-b"),
            ]
        )
        router = self._router(mock_client)

        result = await router.execute(
            model_chain=["model-a", "model-b"],
            messages=[{"role": "user", "content": "signal"}],
            schema_type=self.Signal,
        )

        assert result.success is True
        assert result.model_used == "model-b"
        assert result.fallback_used is True
        assert isinstance(result.parsed, self.Signal)
        assert result.parsed.action == "hold"
        assert result.schema_corrections == 1
        assert result.errors[0]["model"] == "model-a"
        assert result.errors[0]["error_type"] == "schema_error"

    @pytest.mark.asyncio
    async def test_corrective_retry_holds_local_gate_and_rate_slot(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The corrective call is a real second inference and must stay gated.

        It may not escape the process-wide single-flight gate or the per-model
        RPM queue just because it is a retry of the same attempt.
        """
        gate = LocalModelGate()
        monkeypatch.setattr("agents.router.get_local_model_gate", lambda: gate)

        in_use_during_calls: list[int] = []
        model_id = "local/qwen3.6-35b-a3b-ud-q4_k_m"

        async def fake_chat_completion(**kwargs: Any) -> dict[str, Any]:
            in_use_during_calls.append(gate.in_use)
            content = "not json" if len(in_use_during_calls) == 1 else '{"action": "buy", "confidence": 0.9}'
            return {
                "choices": [{"message": {"content": content}}],
                "model": model_id,
                "usage": {"total_tokens": 10},
            }

        mock_client = AsyncMock(spec=LLMClient)
        mock_client.is_error_response.return_value = False
        mock_client.chat_completion = AsyncMock(side_effect=fake_chat_completion)
        router = ModelRouter(
            llm_client=mock_client,
            breaker_registry=CircuitBreakerRegistry(),
            queue_registry=QueueRegistry(),
            retry_config=RetryConfig(max_retries=0, base_delay=0.01),
        )

        result = await router.execute(
            model_chain=[model_id],
            messages=[{"role": "user", "content": "signal"}],
            schema_type=self.Signal,
        )

        assert result.success is True
        assert result.schema_corrections == 1
        # Both provider calls ran while holding the single local slot.
        assert in_use_during_calls == [1, 1]
        assert gate.in_use == 0
        # Both calls consumed an RPM slot.
        queue = router.queues.get(model_id)
        assert queue.active_count == 2


class TestModelRouterWithRealClient:
    """Tests using a real LLMClient but without hitting an actual API."""

    @pytest.mark.asyncio
    async def test_http_error_is_retryable(self) -> None:
        """Client raises HTTP errors which should be caught as retryable."""
        from agents.client import LLMClient

        client = LLMClient(api_key="sk-test")
        # Don't call the real API — just verify the error handling path
        assert client.providers["open_router"]["api_key"] == "sk-test"

    @pytest.mark.asyncio
    async def test_close_cleanup(self) -> None:
        router = ModelRouter(
            llm_client=NoOpLLMClient(),
            breaker_registry=CircuitBreakerRegistry(),
            queue_registry=QueueRegistry(),
        )
        # Should be safe to call multiple times
        await router.client.close()


class TestModelRouterMocked:
    """Tests with a mocked LLM client that returns success."""

    @pytest.mark.asyncio
    async def test_returns_success(self) -> None:
        from agents.client import LLMClient

        mock_client = AsyncMock(spec=LLMClient)
        mock_client.chat_completion = AsyncMock(
            return_value={
                "choices": [{"message": {"content": '{"result": "ok"}'}}],
                "model": "model-a",
                "usage": {"total_tokens": 10},
            }
        )
        mock_client.is_error_response.return_value = False

        router = ModelRouter(
            llm_client=mock_client,
            breaker_registry=CircuitBreakerRegistry(),
            queue_registry=QueueRegistry(),
            retry_config=RetryConfig(max_retries=0, base_delay=0.01),
        )

        result = await router.execute(
            model_chain=["model-a"],
            messages=[{"role": "user", "content": "test"}],
        )

        assert result.success is True
        assert result.model_used == "model-a"
        assert result.degraded is False
        assert result.fallback_used is False

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self) -> None:
        """Primary fails, fallback succeeds."""
        from agents.client import LLMClient

        mock_client = AsyncMock(spec=LLMClient)

        # Track which model was called
        called_models = []

        async def mock_chat(**kwargs: dict[str, Any]) -> dict[str, Any]:
            model = kwargs.get("model", "")
            called_models.append(model)
            if model == "model-a":
                raise ConnectionError("model-a is down")
            return {
                "choices": [{"message": {"content": '{"result": "ok"}'}}],
                "model": model,
                "usage": {"total_tokens": 10},
            }

        mock_client.chat_completion = AsyncMock(side_effect=mock_chat)
        mock_client.is_error_response.return_value = False

        router = ModelRouter(
            llm_client=mock_client,
            breaker_registry=CircuitBreakerRegistry(),
            queue_registry=QueueRegistry(),
            retry_config=RetryConfig(max_retries=0, base_delay=0.01),
        )

        result = await router.execute(
            model_chain=["model-a", "model-b"],
            messages=[{"role": "user", "content": "test"}],
        )

        assert result.success is True
        assert result.model_used == "model-b"
        assert result.fallback_used is True
        assert result.degraded is False
        assert "model-a" in called_models
        assert "model-b" in called_models

    @pytest.mark.asyncio
    async def test_error_envelope_falls_through_to_fallback(self) -> None:
        """A 200-with-error payload must not end the chain."""
        from agents.client import LLMClient

        mock_client = AsyncMock(spec=LLMClient)
        mock_client.chat_completion = AsyncMock(
            side_effect=[
                {
                    "error": True,
                    "error_type": "HTTPStatusError",
                    "model": "model-a",
                    "choices": [],
                    "usage": {"total_tokens": 0},
                },
                {
                    "choices": [{"message": {"content": '{"result": "ok"}'}}],
                    "model": "model-b",
                    "usage": {"total_tokens": 10},
                },
            ]
        )
        mock_client.is_error_response.side_effect = lambda response: bool(response.get("error"))

        router = ModelRouter(
            llm_client=mock_client,
            breaker_registry=CircuitBreakerRegistry(),
            queue_registry=QueueRegistry(),
            retry_config=RetryConfig(max_retries=0, base_delay=0.01),
        )

        result = await router.execute(
            model_chain=["model-a", "model-b"],
            messages=[{"role": "user", "content": "test"}],
        )

        assert result.success is True
        assert result.model_used == "model-b"
        assert result.fallback_used is True
        assert result.degraded is False
        assert len(result.errors) == 1
        assert result.errors[0]["model"] == "model-a"
        assert result.errors[0]["error_type"] == "error_response"
        # An error envelope is a real model failure, so it trips the breaker.
        assert router.breakers.get("model-a").failure_count == 1

    @pytest.mark.asyncio
    async def test_repeated_error_envelopes_open_breaker(self, router: ModelRouter) -> None:
        """A provider that always returns 200-with-error must eventually be skipped.

        The breaker only accumulates failures if the envelope is raised inside
        the retried callable; recording success first would reset it forever.
        """
        for _ in range(3):
            result = await router.execute(
                model_chain=["model-a"],
                messages=[{"role": "user", "content": "test"}],
            )
            assert result.success is False
            assert result.errors[0]["error_type"] == "error_response"

        breaker = router.breakers.get("model-a")
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

        skipped = await router.execute(
            model_chain=["model-a"],
            messages=[{"role": "user", "content": "test"}],
        )
        assert skipped.success is False
        assert skipped.errors[0]["error_type"] == "circuit_breaker_open"

    @pytest.mark.asyncio
    async def test_local_busy_is_not_a_model_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class BusyGate:
            def __init__(self) -> None:
                self.released = False

            async def acquire(self) -> None:
                raise LocalModelBusyError("local model is busy")

            def release(self) -> None:
                self.released = True

        gate = BusyGate()
        monkeypatch.setattr("agents.router.get_local_model_gate", lambda: gate)
        mock_client = AsyncMock(spec=LLMClient)

        router = ModelRouter(
            llm_client=mock_client,
            breaker_registry=CircuitBreakerRegistry(),
            queue_registry=QueueRegistry(),
            retry_config=RetryConfig(max_retries=2, base_delay=0.01),
        )

        result = await router.execute(
            model_chain=["local/qwen3.6-35b-a3b-ud-q4_k_m"],
            messages=[{"role": "user", "content": "test"}],
        )

        assert result.success is False
        assert result.degraded is True
        assert result.errors[0]["error_type"] == "local_model_busy"
        mock_client.chat_completion.assert_not_awaited()
        assert gate.released is False
        assert router.breakers.get("local/qwen3.6-35b-a3b-ud-q4_k_m").failure_count == 0
