"""Chat API router.

Endpoints:
    POST /api/v1/chat — send a bounded conversation to the read-only assistant

This router has no execution path. It cannot place an order, change a mode,
promote a strategy, or touch the kill switch.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services import chat_service

logger = logging.getLogger("ares.api.chat")

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_UNAVAILABLE = "Chat model unavailable; try again later"


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    """Return one assistant reply for the supplied conversation history."""
    try:
        return await chat_service.get_chat_service().reply(payload.messages)
    except chat_service.ChatUnavailableError as exc:
        logger.warning("Chat request failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNAVAILABLE,
        ) from exc
