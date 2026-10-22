"""Tests for the read-only chat service."""

from __future__ import annotations

from typing import Any

import pytest

from agents.models import AgentModelConfig, ModelRoster, load_model_roster
from agents.router import RouterResult
from backend.schemas.chat import ChatTurn
from backend.services import chat_service
from backend.services.chat_service import (
    SYSTEM_PROMPT,
    ChatService,
    ChatUnavailableError,
)


class FakeClient:
    def __init__(self, content: str | None = "A grounded reply", *, error: bool = False) -> None:
        self.content = content
        self.error = error

    def is_error_response(self, response: dict[str, Any]) -> bool:
        return self.error

    def parse_content(self, response: dict[str, Any]) -> str | None:
        return self.content


class FakeRouter:
    def __init__(self, result: RouterResult, client: FakeClient | None = None) -> None:
        self.result = result
        self.client = client or FakeClient()
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> RouterResult:
        self.calls.append(kwargs)
        return self.result


def _config() -> AgentModelConfig:
    return AgentModelConfig(
        agent_name="chat",
        primary="primary-model",
        fallbacks=["fallback-model"],
        timeout=45,
        rpm=7,
        temperature=0.2,
        max_tokens=123,
        universal_fallback="universal-model",
    )


def _result(
    *,
    success: bool = True,
    content: str | None = "A grounded reply",
    fallback_used: bool = False,
) -> RouterResult:
    result = RouterResult()
    result.success = success
    result.model_used = "fallback-model" if fallback_used else "primary-model"
    result.fallback_used = fallback_used
    result.response = {"choices": [{"message": {"content": content}}]}
    return result


def _messages() -> list[ChatTurn]:
    return [
        ChatTurn(role="user", content="How does the risk gate work?"),
        ChatTurn(role="assistant", content="It checks exposure and drawdown."),
        ChatTurn(role="user", content="What about consensus?"),
    ]


async def test_reply_sends_system_prompt_then_history_with_config() -> None:
    router = FakeRouter(_result(fallback_used=True))
    service = ChatService(router=router, model_config=_config())  # type: ignore[arg-type]

    response = await service.reply(_messages())

    assert response.reply == "A grounded reply"
    assert response.model == "fallback-model"
    assert response.fallback_used is True

    call = router.calls[0]
    assert call["model_chain"] == ["primary-model", "fallback-model", "universal-model"]
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 123
    assert call["rpm"] == 7
    assert call["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert call["messages"][1:] == [
        {"role": "user", "content": "How does the risk gate work?"},
        {"role": "assistant", "content": "It checks exposure and drawdown."},
        {"role": "user", "content": "What about consensus?"},
    ]


async def test_reply_rejects_an_exhausted_chain() -> None:
    router = FakeRouter(_result(success=False))
    service = ChatService(router=router, model_config=_config())  # type: ignore[arg-type]

    with pytest.raises(ChatUnavailableError, match="unavailable"):
        await service.reply(_messages())


async def test_reply_rejects_an_error_envelope() -> None:
    router = FakeRouter(_result(), client=FakeClient(error=True))
    service = ChatService(router=router, model_config=_config())  # type: ignore[arg-type]

    with pytest.raises(ChatUnavailableError):
        await service.reply(_messages())


@pytest.mark.parametrize("content", [None, "", "   "])
async def test_reply_rejects_empty_content(content: str | None) -> None:
    router = FakeRouter(_result(content=content), client=FakeClient(content=content))
    service = ChatService(router=router, model_config=_config())  # type: ignore[arg-type]

    with pytest.raises(ChatUnavailableError, match="empty"):
        await service.reply(_messages())


def test_real_roster_has_a_free_chat_chain() -> None:
    config = load_model_roster().get("chat")

    assert config.model_chain
    assert all(model.endswith((":free", "/free")) for model in config.model_chain)
    assert config.temperature <= 1.0
    assert config.max_tokens > 0


def test_get_chat_service_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    roster = ModelRoster({"chat": _config()})
    client = FakeClient()

    monkeypatch.setattr(chat_service, "load_model_roster", lambda: roster)
    monkeypatch.setattr(chat_service, "create_llm_client", lambda: client)
    chat_service.reset_chat_service()

    try:
        first = chat_service.get_chat_service()
        second = chat_service.get_chat_service()
        assert first is second
        assert first.model_chain == ["primary-model", "fallback-model", "universal-model"]
    finally:
        chat_service.reset_chat_service()
