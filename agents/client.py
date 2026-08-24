"""Generic async HTTP client for LLM API calls.

Supports OpenRouter and OpenCode-compatible APIs.
Handles timeouts, retryable errors, and graceful degradation.
"""

from __future__ import annotations

import json
import logging
import os
import time
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
                    "api_key": api_key or "",
                    "base_url": base_url or os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),  # type: ignore[dict-item]
                }
            if "default" not in self.providers:
                self.providers["default"] = self.providers["open_router"]

        # Populate from env if not provided
        self._populate_from_env()

        self._clients: dict[str, httpx.AsyncClient] = {}
        self._circuit_breakers: dict[str, dict[str, Any]] = {}

    def _check_circuit_breaker(self, model: str) -> None:
        cb = self._circuit_breakers.get(model)
        if cb and cb["failures"] >= 3:
            if time.time() - cb["last_failure"] < 60:
                raise ValueError(f"Circuit breaker open for model {model}")

    def _record_success(self, model: str) -> None:
        if model in self._circuit_breakers:
            self._circuit_breakers[model]["failures"] = 0

    def _record_failure(self, model: str) -> None:
        if model not in self._circuit_breakers:
            self._circuit_breakers[model] = {"failures": 0, "last_failure": 0}
        self._circuit_breakers[model]["failures"] += 1
        self._circuit_breakers[model]["last_failure"] = time.time()

    def _is_valid_key(self, key: str | None) -> bool:
        if not key:
            return False
        k = key.strip().lower()
        if not k or k in ["", "changeme", "placeholder", "dummy", "your_api_key_here"]:
            return False
        return True

    def _populate_from_env(self) -> None:
        # Free-only OpenRouter runtime: ONLY the OpenRouter provider is ever
        # configured. OpenCode / Gemini / Mistral are intentionally absent so
        # a paid or third-party request can never be sent.
        env_map = {
            "open_router": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        }
        for provider, (key_env, url_env, default_url) in env_map.items():
            if provider not in self.providers:
                key = os.getenv(key_env)
                if self._is_valid_key(key):
                    self.providers[provider] = {
                        "api_key": key.strip(),  # type: ignore[union-attr]
                        "base_url": os.getenv(url_env, default_url).rstrip("/"),
                    }

    def _get_client(self, provider: str) -> httpx.AsyncClient:
        if provider not in self._clients:
            config = self.providers.get(provider) or self.providers.get("default")
            if not config:
                # Fallback to OpenRouter default if no config found
                config = {"api_key": "", "base_url": "https://openrouter.ai/api/v1"}

            api_key = config.get("api_key", "").strip()
            headers = {
                "Content-Type": "application/json",
            }
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
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
        elif clean_model.startswith(("opencode/", "google/", "mistral/")):
            # Free-only OpenRouter runtime: a non-OpenRouter model must never
            # reach the wire. Fail closed instead of sending a paid request.
            raise ValueError(f"Provider not allowed in free-only OpenRouter runtime: {clean_model}")

        self._check_circuit_breaker(model)
        client = self._get_client(provider)

        # Structured output: if the caller supplies a JSON Schema dict, request
        # a guaranteed-JSON response via OpenRouter's response_format.
        structured_schema = kwargs.pop("json_schema", None)

        payload: dict[str, Any] = {
            "model": clean_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        if provider == "open_router":
            # Hard zero-price bound — OpenRouter rejects with 402 if the chosen
            # model would cost more than this, guaranteeing a free-only request.
            payload["max_price"] = {
                "prompt": 0,
                "completion": 0,
                "request": 0,
                "image": 0,
            }
            if structured_schema is not None:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_output",
                        "strict": True,
                        "schema": structured_schema,
                    },
                }

        try:
            response = await client.post(
                "/chat/completions",
                json=payload,
                timeout=timeout or self.default_timeout,
            )
            response.raise_for_status()

            if provider == "google":
                self._google_429_count = 0

            response_json = response.json()

            # Catch OpenRouter downstream errors hidden in 200 OK responses
            if provider == "open_router" and isinstance(response_json, dict) and "error" in response_json:
                error_msg = response_json["error"]
                logger.error(f"OpenRouter downstream payload error: {error_msg}")
                self._record_failure(model)
                raise ValueError(f"OpenRouter payload error: {error_msg}")

            self._record_success(model)
            return response_json  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [429, 503, 529]:
                logger.warning(
                    f"Provider '{provider}' rate limited or down ({e.response.status_code}). "
                    "Triggering router fallback chain."
                )
                self._record_failure(model)
                import asyncio

                await asyncio.sleep(5)
            else:
                logger.error(f"HTTP error from provider '{provider}': {e.response.text}")
                self._record_failure(model)
            raise e
        except Exception as e:
            logger.error(f"Unexpected connection error with provider '{provider}': {str(e)}")
            self._record_failure(model)
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
            logger.error(f"Unhandled exception: {e}", exc_info=True)
            error_type = type(e).__name__
            resp = getattr(e, "response", None)
            status_code = resp.status_code if resp is not None else None
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
            return response["choices"][0]["message"]["content"]  # type: ignore[no-any-return]
        except (KeyError, IndexError, TypeError):
            return None

    def is_error_response(self, response: dict[str, Any]) -> bool:
        """Check if the response is an error envelope."""
        return response.get("error", False)  # type: ignore[no-any-return]

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
                        "content": json.dumps(
                            {
                                "error": "LLM client not configured — no API key",
                                "degraded": True,
                            }
                        )
                    }
                }
            ],
            "usage": {"total_tokens": 0},
        }

    def parse_content(self, response: dict[str, Any]) -> str | None:
        try:
            return response["choices"][0]["message"]["content"]  # type: ignore[no-any-return]
        except (KeyError, IndexError, TypeError):
            return None

    def is_error_response(self, response: dict[str, Any]) -> bool:
        return True

    async def close(self) -> None:
        pass


def _is_valid_key(key: str | None) -> bool:
    if not key:
        return False
    k = key.strip().lower()
    if not k or k in ["", "changeme", "placeholder", "dummy", "your_api_key_here"]:
        return False
    return True


def create_llm_client() -> LLMClient | NoOpLLMClient:
    """Create the appropriate LLM client based on available configuration.

    Enforces the free-only OpenRouter runtime:
        - OpenRouter is the ONLY provider that may be selected.
        - ``llm_free_only`` and ``llm_paper_only`` are hard operating bounds.
    """
    from backend.core.config import settings

    if settings.llm_free_only and settings.llm_provider != "openrouter":
        raise RuntimeError(
            "llm_free_only=true but llm_provider != 'openrouter'. "
            "The free-only OpenRouter paper-trading runtime refuses other providers."
        )

    providers = {}
    if _is_valid_key(settings.openrouter_api_key):
        providers["open_router"] = {
            "api_key": settings.openrouter_api_key.strip(),
            "base_url": settings.openrouter_base_url,
        }

    if providers:
        return LLMClient(providers=providers)

    # No OpenRouter key configured (offline/dev). Fall back to env lookup via
    # LLMClient default init; otherwise degrade to NoOp (never a paid request).
    client = LLMClient()
    if client.providers:
        return client

    return NoOpLLMClient()
