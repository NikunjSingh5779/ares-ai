"""Chat request/response schemas.

The chat endpoint is read-only. It never accepts an order, an approval, a
position size, or a live-trading flag; the trading path remains the only way to
create a trade and keeps every safety gate.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ChatRole = Literal["user", "assistant"]

# A single turn is bounded so one request cannot consume the whole context
# window or turn the endpoint into a bulk text sink.
ChatContent = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class ChatTurn(BaseModel):
    """One user or assistant message in the conversation."""

    model_config = ConfigDict(extra="forbid")

    role: ChatRole
    content: ChatContent


class ChatRequest(BaseModel):
    """A bounded conversation history ending with a user message."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatTurn] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Recent conversation turns, oldest first; the last must be from the user",
    )

    @model_validator(mode="after")
    def _last_turn_is_user(self) -> ChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("The last chat turn must be from the user")
        return self


class ChatResponse(BaseModel):
    """A model reply plus the model/fallback metadata used to produce it."""

    reply: str = Field(..., min_length=1, max_length=8000)
    model: str = Field(..., min_length=1)
    fallback_used: bool = False
