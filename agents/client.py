"""Generic async HTTP client for LLM API calls.

Supports OpenRouter and OpenCode-compatible APIs.
Handles timeouts, retryable errors, and graceful degradation.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx


class LLMClient:
    """Async HTTP client for LLM chat completion APIs.

    Communicates with OpenRouter/OpenCode-compatible endpoints.
    Falls back to graceful degradation when the API is unavailable.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_timeout: int = 60,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENCODE_API_KEY") or ""
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
        self.default_timeout = default_timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.default_timeout,
            )
        return self._client

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
        client = await self._get_client()

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        response = await client.post(
            "/chat/completions",
            json=payload,
            timeout=timeout or self.default_timeout,
        )
        response.raise_for_status()
        return response.json()

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
        if self._client is not None:
            await self._client.aclose()
            self._client = None


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
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENCODE_API_KEY")
    if api_key:
        return LLMClient(api_key=api_key)
    return NoOpLLMClient()
