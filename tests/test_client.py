"""Tests for LLM client."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from agents.client import LLMClient, NoOpLLMClient, create_llm_client
from agents.models import load_model_roster


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

    @pytest.mark.asyncio
    async def test_local_provider_strips_prefix_sets_reasoning_off_and_omits_auth(
        self,
        httpx_mock: HTTPXMock,
    ) -> None:
        httpx_mock.add_response(
            url="http://local.test/v1/chat/completions",
            method="POST",
            json={"choices": [{"message": {"content": "ok"}}]},
        )
        client = LLMClient(
            providers={
                "local": {
                    "api_key": "",
                    "base_url": "http://local.test/v1/",
                    "timeout": 3,
                }
            }
        )

        response = await client.chat_completion(
            model="local/qwen3.6-35b-a3b-ud-q4_k_m",
            messages=[{"role": "user", "content": "hello"}],
        )
        await client.close()

        assert response["choices"][0]["message"]["content"] == "ok"
        request = httpx_mock.get_request()
        assert request is not None
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3.6-35b-a3b-ud-q4_k_m"
        assert payload["reasoning_effort"] == "off"
        assert "authorization" not in request.headers


class TestFreeOnlyModelPolicy:
    """The free-only policy is enforced before any network client is built."""

    @pytest.mark.asyncio
    async def test_paid_hosted_model_is_blocked_before_network(self) -> None:
        client = LLMClient(api_key="sk-test-key")
        with pytest.raises(ValueError, match="free-only policy"):
            await client.chat_completion(
                model="open_router/openai/gpt-4o",
                messages=[{"role": "user", "content": "hello"}],
            )
        assert client._clients == {}

    @pytest.mark.asyncio
    async def test_paid_opencode_model_is_blocked(self) -> None:
        client = LLMClient(providers={"opencode": {"api_key": "test", "base_url": "https://api.opencode.ai/v1"}})
        with pytest.raises(ValueError, match="free-only policy"):
            await client.chat_completion(model="opencode/gpt-5", messages=[])

    @pytest.mark.asyncio
    async def test_direct_google_model_is_blocked(self) -> None:
        client = LLMClient(
            providers={
                "google": {"api_key": "test", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"}
            }
        )
        with pytest.raises(ValueError, match="free-only model policy"):
            await client.chat_completion(model="google/gemini-2.5-pro", messages=[])

    @pytest.mark.asyncio
    async def test_local_model_without_configuration_is_blocked(self) -> None:
        client = LLMClient()
        with pytest.raises(ValueError, match="LOCAL_LLM_BASE_URL"):
            await client.chat_completion(model="local/qwen", messages=[])

    @pytest.mark.asyncio
    async def test_free_hosted_model_is_allowed(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            method="POST",
            json={"choices": [{"message": {"content": "ok"}}]},
        )
        client = LLMClient(api_key="sk-test-key")
        response = await client.chat_completion(
            model="open_router/nvidia/nemotron-3-super-120b-a12b:free",
            messages=[{"role": "user", "content": "hello"}],
            provider={"sort": "price"},
        )
        await client.close()

        assert response["choices"][0]["message"]["content"] == "ok"
        request = httpx_mock.get_request()
        assert request is not None
        payload = json.loads(request.content)
        # max_price belongs inside OpenRouter's provider preferences, not at
        # the top level, and caller preferences must survive the merge.
        assert "max_price" not in payload
        assert payload["provider"] == {
            "sort": "price",
            "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0},
        }

    @pytest.mark.asyncio
    async def test_local_error_envelope_is_raised(self, httpx_mock: HTTPXMock) -> None:
        """A local server can return 200 with an error body; do not pass it through."""
        httpx_mock.add_response(
            url="http://local.test/v1/chat/completions",
            method="POST",
            json={"error": {"message": "model not loaded"}},
        )
        client = LLMClient(providers={"local": {"api_key": "", "base_url": "http://local.test/v1"}})
        with pytest.raises(ValueError, match="local payload error"):
            await client.chat_completion(model="local/qwen", messages=[])
        await client.close()


class TestFreeOnlyModelRoster:
    def test_every_hosted_model_is_explicitly_free(self) -> None:
        roster = load_model_roster()
        for agent_name in roster.agent_names:
            for model_id in roster.get(agent_name).model_chain:
                if model_id.startswith("open_router/"):
                    hosted_id = model_id.removeprefix("open_router/")
                    assert hosted_id.endswith(":free") or hosted_id == "openrouter/free", (
                        f"{agent_name} uses an unverified model: {model_id}"
                    )
                elif model_id.startswith("opencode/"):
                    assert model_id.endswith("-free"), f"{agent_name} uses an unverified OpenCode model: {model_id}"
                else:
                    assert model_id.startswith("local/"), f"{agent_name} uses a non-allowlisted model: {model_id}"


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
        for k in ["OPENROUTER_API_KEY", "OPENCODE_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY"]:
            monkeypatch.delenv(k, raising=False)

        # Also mock settings since create_llm_client uses it now
        from backend.core.config import settings

        monkeypatch.setattr(settings, "openrouter_api_key", "")
        monkeypatch.setattr(settings, "opencode_api_key", "")
        monkeypatch.setattr(settings, "gemini_api_key", "")
        monkeypatch.setattr(settings, "mistral_api_key", "")
        monkeypatch.setattr(settings, "local_llm_enabled", False)

        client = create_llm_client()
        assert isinstance(client, NoOpLLMClient)

    def test_creates_local_client_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Local is opt-in, needs no API key, and carries its own timeout."""
        for key in ["OPENROUTER_API_KEY", "OPENCODE_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY"]:
            monkeypatch.delenv(key, raising=False)

        from backend.core.config import settings

        monkeypatch.setattr(settings, "openrouter_api_key", "")
        monkeypatch.setattr(settings, "opencode_api_key", "")
        monkeypatch.setattr(settings, "gemini_api_key", "")
        monkeypatch.setattr(settings, "mistral_api_key", "")
        monkeypatch.setattr(settings, "local_llm_enabled", True)
        monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:8080/v1/")
        monkeypatch.setattr(settings, "local_llm_timeout_seconds", 90.0)

        client = create_llm_client()

        assert isinstance(client, LLMClient)
        assert "open_router" not in client.providers
        assert client.providers["local"] == {
            "api_key": "",
            "base_url": "http://127.0.0.1:8080/v1",
            "timeout": 90.0,
        }
