"""Tests for the read-only chat API."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import chat as chat_router
from backend.schemas.chat import ChatResponse
from backend.services import chat_service
from backend.services.chat_service import ChatUnavailableError


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_router.router)
    return TestClient(app)


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    service = AsyncMock()
    service.reply = AsyncMock(
        return_value=ChatResponse(reply="Risk checks exposure and drawdown.", model="free-model", fallback_used=False)
    )
    monkeypatch.setattr(chat_service, "get_chat_service", lambda: service)
    return service


def _payload() -> dict[str, object]:
    return {
        "messages": [
            {"role": "user", "content": "How does the risk gate work?"},
            {"role": "assistant", "content": "It checks exposure and drawdown."},
            {"role": "user", "content": "And consensus?"},
        ]
    }


def test_chat_returns_the_model_reply(client: TestClient, fake_service: AsyncMock) -> None:
    response = client.post("/api/v1/chat", json=_payload())

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Risk checks exposure and drawdown.",
        "model": "free-model",
        "fallback_used": False,
    }
    turns = fake_service.reply.await_args.args[0]
    assert [turn.role for turn in turns] == ["user", "assistant", "user"]


def test_chat_returns_503_when_the_model_chain_fails(client: TestClient, fake_service: AsyncMock) -> None:
    fake_service.reply.side_effect = ChatUnavailableError("all models exhausted")

    response = client.post("/api/v1/chat", json=_payload())

    assert response.status_code == 503
    assert response.json()["detail"] == "Chat model unavailable; try again later"


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": []},
        {"messages": [{"role": "assistant", "content": "No user turn"}]},
        {"messages": [{"role": "user", "content": "   "}]},
        {"messages": [{"role": "user", "content": "x" * 4001}]},
        {"messages": [{"role": "system", "content": "not allowed"}]},
        {"messages": [{"role": "user", "content": "hi"}], "status": "approved"},
    ],
)
def test_chat_rejects_invalid_history(client: TestClient, fake_service: AsyncMock, payload: dict[str, object]) -> None:
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 422
    fake_service.reply.assert_not_awaited()


def test_chat_rejects_more_than_twenty_turns(client: TestClient, fake_service: AsyncMock) -> None:
    messages = [{"role": "user", "content": f"turn {index}"} for index in range(21)]

    response = client.post("/api/v1/chat", json={"messages": messages})

    assert response.status_code == 422
    fake_service.reply.assert_not_awaited()
