"""Tests for LLM client."""
from __future__ import annotations

import pytest

from agents.client import LLMClient, NoOpLLMClient, create_llm_client


class TestLLMClientInit:
    def test_initializes_with_defaults(self) -> None:
        client = LLMClient()
        assert client.api_key == ""  # no env var set
        assert client.base_url == "https://openrouter.ai/api/v1"
        assert client.default_timeout == 60

    def test_initializes_with_custom_values(self) -> None:
        client = LLMClient(
            api_key="sk-test-key",
            base_url="https://api.test.com/v1",
            default_timeout=120,
        )
        assert client.api_key == "sk-test-key"
        assert client.base_url == "https://api.test.com/v1"
        assert client.default_timeout == 120


class TestNoOpLLMClient:
    @pytest.mark.asyncio
    async def test_chat_completion_returns_degraded(self) -> None:
        client = NoOpLLMClient()
        response = await client.chat_completion(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert response.get("error") is True
        assert response.get("error_type") == "NoOpClient"
        assert response.get("model") == "test-model"

    @pytest.mark.asyncio
    async def test_parse_content(self) -> None:
        client = NoOpLLMClient()
        response = await client.chat_completion(model="test", messages=[])
        content = client.parse_content(response)
        assert content is not None
        assert "LLM client not configured" in content

    def test_is_error_response_always_true(self) -> None:
        client = NoOpLLMClient()
        assert client.is_error_response({}) is True

    @pytest.mark.asyncio
    async def test_chat_completion_with_fallback(self) -> None:
        client = NoOpLLMClient()
        response = await client.chat_completion_with_fallback(
            model="test", messages=[{"role": "user", "content": "hi"}]
        )
        assert response.get("error") is True

    @pytest.mark.asyncio
    async def test_close_is_noop(self) -> None:
        client = NoOpLLMClient()
        await client.close()  # should not raise


class TestCreateLLMClient:
    def test_creates_noop_without_api_key(self) -> None:
        """Without env vars, create_llm_client returns NoOpLLMClient."""
        client = create_llm_client()
        assert isinstance(client, NoOpLLMClient)
