"""Generic async HTTP client for LLM API calls.

Supports OpenRouter and OpenCode-compatible APIs.
Handles timeouts, retryable errors, and graceful degradation.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMClient:
    """Async HTTP client for LLM chat completion APIs.

    Communicates with OpenRouter/OpenCode-compatible endpoints.
    Falls back to graceful degradation when the API is unavailable.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        providers: dict[str, dict[str, str]] | None = None,
        default_timeout: int = 60,
    ) -> None:
        self.default_timeout = default_timeout
        self.providers = providers or {}
        
        # Legacy support for tests that just pass api_key
        if api_key:
            if "open_router" not in self.providers:
                self.providers["open_router"] = {
                    "api_key": api_key,
                    "base_url": base_url or os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
                }
            if "default" not in self.providers:
                self.providers["default"] = self.providers["open_router"]
                
        # Populate from env if not provided
        self._populate_from_env()

        self._clients: dict[str, httpx.AsyncClient] = {}

    def _populate_from_env(self) -> None:
        env_map = {
            "open_router": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            "opencode": ("OPENCODE_API_KEY", "OPENCODE_BASE_URL", "https://api.opencode.ai/v1"),
            "google": ("GEMINI_API_KEY", "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
            "mistral": ("MISTRAL_API_KEY", "MISTRAL_BASE_URL", "https://api.mistral.ai/v1"),
        }
        for provider, (key_env, url_env, default_url) in env_map.items():
            if provider not in self.providers:
                key = os.getenv(key_env)
                if key:
                    self.providers[provider] = {
                        "api_key": key,
                        "base_url": os.getenv(url_env, default_url).rstrip("/")
                    }

    def _get_client(self, provider: str) -> httpx.AsyncClient:
        if provider not in self._clients:
            config = self.providers.get(provider) or self.providers.get("default")
            if not config:
                # Fallback to OpenRouter default if no config found
                config = {
                    "api_key": "",
                    "base_url": "https://openrouter.ai/api/v1"
                }
            
            headers = {
                "Authorization": f"Bearer {config.get('api_key', '')}",
                "Content-Type": "application/json",
            }
            if provider == "open_router":
                headers["HTTP-Referer"] = "https://localhost:3000"
                headers["X-Title"] = "BacktestEngine"
                
            self._clients[provider] = httpx.AsyncClient(
                base_url=config.get("base_url", ""),
                headers=headers,
                timeout=self.default_timeout,
            )
        return self._clients[provider]

    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat completion request.

        Args:
            model: Model identifier (e.g. "openai/gpt-4o").
            messages: List of {"role": ..., "content": ...} dicts.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.
            timeout: Request timeout in seconds. Uses default if None.
            **kwargs: Additional parameters passed to the API.

        Returns:
            Raw API response dict with "choices", "model", "usage", etc.

        Raises:
            httpx.HTTPStatusError: On non-2xx status.
            httpx.TimeoutException: On timeout.
            httpx.RequestError: On connection/network errors.
        """
        # Strip provider prefixes if present and determine provider
        clean_model = model
        provider = "default"
        
        if clean_model.startswith("open_router/"):
            clean_model = clean_model.replace("open_router/", "", 1)
            provider = "open_router"
        elif clean_model.startswith("opencode/"):
            clean_model = clean_model.replace("opencode/", "", 1)
            provider = "opencode"
        elif clean_model.startswith("google/"):
            clean_model = clean_model.replace("google/", "", 1)
            provider = "google"
        elif clean_model.startswith("mistral/"):
            clean_model = clean_model.replace("mistral/", "", 1)
            provider = "mistral"

        client = self._get_client(provider)

        payload: dict[str, Any] = {
            "model": clean_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        try:
            response = await client.post(
                "/chat/completions",
                json=payload,
                timeout=timeout or self.default_timeout,
            )
            response.raise_for_status()
            response_json = response.json()
            
            # Catch OpenRouter downstream errors hidden in 200 OK responses
            if provider == "open_router" and isinstance(response_json, dict) and "error" in response_json:
                error_msg = response_json["error"]
                logger.error(f"OpenRouter downstream payload error: {error_msg}")
                raise ValueError(f"OpenRouter payload error: {error_msg}")
                
            return response_json
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [429, 503, 529]:
                logger.warning(f"Provider '{provider}' rate limited or down ({e.response.status_code}). Triggering router fallback chain.")
            else:
                logger.error(f"HTTP error from provider '{provider}': {e.response.text}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected connection error with provider '{provider}': {str(e)}")
            raise e

    async def chat_completion_with_fallback(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat completion, returning an error dict on failure.

        Returns the raw response on success.
        On any exception, returns an error-envelope dict so callers can
        handle gracefully without try/except.
        """
        try:
            return await self.chat_completion(model, messages, **kwargs)
        except Exception as e:
            error_type = type(e).__name__
            status_code = getattr(e, "response", None) and e.response.status_code  # type: ignore[union-attr]
            return {
                "error": True,
                "error_type": error_type,
                "status_code": status_code,
                "model": model,
                "choices": [],
                "usage": {"total_tokens": 0},
            }

    def parse_content(self, response: dict[str, Any]) -> str | None:
        """Extract text content from a chat completion response."""
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

    def is_error_response(self, response: dict[str, Any]) -> bool:
        """Check if the response is an error envelope."""
        return response.get("error", False)

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


class NoOpLLMClient:
    """LLM client that returns graceful degradation responses.

    Used when no API key is configured.
    Enables offline development and testing.
    """

    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._degraded_response(model)

    async def chat_completion_with_fallback(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._degraded_response(model)

    def _degraded_response(self, model: str) -> dict[str, Any]:
        return {
            "error": True,
            "error_type": "NoOpClient",
            "status_code": None,
            "model": model,
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "error": "LLM client not configured — no API key",
                            "degraded": True,
                        })
                    }
                }
            ],
            "usage": {"total_tokens": 0},
        }

    def parse_content(self, response: dict[str, Any]) -> str | None:
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

    def is_error_response(self, response: dict[str, Any]) -> bool:
        return True

    async def close(self) -> None:
        pass


def create_llm_client() -> LLMClient | NoOpLLMClient:
    """Create the appropriate LLM client based on available configuration."""
    from backend.core.config import settings
    providers = {}
    if settings.openrouter_api_key:
        providers["open_router"] = {"api_key": settings.openrouter_api_key, "base_url": settings.openrouter_base_url}
    if settings.opencode_api_key:
        providers["opencode"] = {"api_key": settings.opencode_api_key, "base_url": settings.opencode_base_url}
    if getattr(settings, "gemini_api_key", ""):
        providers["google"] = {"api_key": settings.gemini_api_key, "base_url": settings.gemini_base_url}
    if getattr(settings, "mistral_api_key", ""):
        providers["mistral"] = {"api_key": settings.mistral_api_key, "base_url": settings.mistral_base_url}
        
    if providers:
        return LLMClient(providers=providers)
    
    # Fallback to env lookup via LLMClient default init
    client = LLMClient()
    if client.providers:
        return client
        
    return NoOpLLMClient()
