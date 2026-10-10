"""Tests for LLM client."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from agents.client import LLMClient, NoOpLLMClient, create_llm_client


class TestLLMClientInit:
    def test_initializes_with_defaults(self) -> None:
        client = LLMClient()
        assert not client.providers.get("open_router", {}).get("api_key")
        assert client.default_timeout == 60

    def test_initializes_with_custom_values(self) -> None:
        client = LLMClient(
            api_key="sk-test-key",
            base_url="https://api.test.com/v1",
            default_timeout=120,
        )
        assert client.providers["open_router"]["api_key"] == "sk-test-key"
        assert client.providers["open_router"]["base_url"] == "https://api.test.com/v1"
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
    def test_creates_noop_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without env vars or settings, create_llm_client returns NoOpLLMClient."""
        # Unset env vars
        for k in [
            "LOCAL_LLM_BASE_URL",
            "LOCAL_LLM_API_KEY",
            "OPENROUTER_API_KEY",
            "OPENCODE_API_KEY",
            "GEMINI_API_KEY",
            "MISTRAL_API_KEY",
        ]:
            monkeypatch.delenv(k, raising=False)

        # Also mock settings since create_llm_client uses it now
        from backend.core.config import settings

        monkeypatch.setattr(settings, "local_llm_base_url", "")
        monkeypatch.setattr(settings, "local_llm_api_key", "")
        monkeypatch.setattr(settings, "openrouter_api_key", "")
        monkeypatch.setattr(settings, "opencode_api_key", "")
        monkeypatch.setattr(settings, "gemini_api_key", "")
        monkeypatch.setattr(settings, "mistral_api_key", "")

        client = create_llm_client()
        assert isinstance(client, NoOpLLMClient)

    def test_creates_local_client_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.core.config import settings

        monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:1919/v1")
        monkeypatch.setattr(settings, "local_llm_api_key", "")
        monkeypatch.setattr(settings, "openrouter_api_key", "")
        monkeypatch.setattr(settings, "opencode_api_key", "")
        monkeypatch.setattr(settings, "gemini_api_key", "")
        monkeypatch.setattr(settings, "mistral_api_key", "")

        client = create_llm_client()
        assert isinstance(client, LLMClient)
        assert client.providers["local"]["base_url"] == "http://127.0.0.1:1919/v1"

    @pytest.mark.asyncio
    async def test_local_auto_discovers_current_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = LLMClient(providers={"local": {"api_key": "", "base_url": "http://local.test/v1"}})
        mock_http = AsyncMock()
        mock_http.get.return_value = httpx.Response(
            200,
            json={"data": [{"id": "Qwen/Qwen3.8-local"}]},
            request=httpx.Request("GET", "http://local.test/v1/models"),
        )
        mock_http.post.return_value = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=httpx.Request("POST", "http://local.test/v1/chat/completions"),
        )
        monkeypatch.setattr(client, "_get_client", lambda provider: mock_http)

        response = await client.chat_completion(
            model="local/auto", messages=[{"role": "user", "content": "hello"}]
        )

        assert response["choices"][0]["message"]["content"] == "ok"
        mock_http.get.assert_awaited_once()
        assert mock_http.post.await_args is not None
        assert mock_http.post.await_args.kwargs["json"]["model"] == "Qwen/Qwen3.8-local"

    @pytest.mark.asyncio
    async def test_paid_hosted_model_is_blocked_before_network(self) -> None:
        client = LLMClient(api_key="sk-test-key")
        with pytest.raises(ValueError, match="free-only policy"):
            await client.chat_completion(
                model="open_router/openai/gpt-4o", messages=[{"role": "user", "content": "hello"}]
            )
        assert client._clients == {}
