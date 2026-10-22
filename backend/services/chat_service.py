"""Read-only conversational chat service.

The service sends a bounded conversation history to the configured fallback
chain and returns the model's text. It has no tools and no execution path: a
chat reply can never create, modify, or cancel an order or change a safety gate.
"""

from __future__ import annotations

import logging

from agents.circuit_breaker import CircuitBreakerRegistry
from agents.client import create_llm_client
from agents.models import AgentModelConfig, load_model_roster
from agents.queue import QueueRegistry
from agents.retry import RetryConfig
from agents.router import ModelRouter
from backend.schemas.chat import ChatResponse, ChatTurn

logger = logging.getLogger("ares.chat")

CHAT_MODEL_KEY = "chat"

SYSTEM_PROMPT = """You are the ARES AI dashboard assistant, a read-only guide to a
paper-trading research platform.

Hard rules:
- You cannot place, modify, or cancel orders, arm or disarm the kill switch,
  change trading modes, promote a strategy, or enable live trading. Never claim
  that you did any of those things.
- Never invent prices, portfolio values, positions, PnL, signals, or backtest
  results. If the user asks for current data, point them to the relevant
  dashboard page (Markets, Portfolio, Risk, Live, Signals, or Backtests) and,
  for a fresh analysis, the Analyze action on Markets.
- Paper trading is the default. Live trading is disabled unless a human enables
  it after the promotion gate; it is never a chat action.
- The Risk agent, the strict >80% Market Analyst and Quant consensus rule, the
  position cap, drawdown limits, and the kill switch are authoritative. Never
  suggest bypassing them.
- Do not ask for API keys, passwords, or other secrets.
- If you are unsure, say so instead of guessing.

Style: concise plain text. Short paragraphs or simple "-" bullet lines; do not
use Markdown tables, headings, or code fences."""


class ChatUnavailableError(RuntimeError):
    """Raised when every configured chat model fails or returns no text."""


class ChatService:
    """Run one bounded chat turn through the model fallback chain."""

    def __init__(self, router: ModelRouter, model_config: AgentModelConfig) -> None:
        self._router = router
        self._config = model_config

    @property
    def model_chain(self) -> list[str]:
        return self._config.model_chain

    async def reply(self, messages: list[ChatTurn]) -> ChatResponse:
        """Return a model reply or raise :class:`ChatUnavailableError`."""
        payload = [{"role": "system", "content": SYSTEM_PROMPT}]
        payload.extend({"role": turn.role, "content": turn.content} for turn in messages)

        result = await self._router.execute(
            model_chain=self.model_chain,
            messages=payload,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            rpm=self._config.rpm,
        )

        response = result.response or {}
        if not result.success or self._router.client.is_error_response(response):
            logger.warning(
                "Chat model chain exhausted",
                extra={"errors": result.errors, "model_used": result.model_used},
            )
            raise ChatUnavailableError("Chat model unavailable")

        content = self._router.client.parse_content(response)
        if not content or not content.strip():
            logger.warning("Chat model returned an empty reply", extra={"model_used": result.model_used})
            raise ChatUnavailableError("Chat model returned an empty reply")

        return ChatResponse(
            reply=content.strip(),
            model=result.model_used,
            fallback_used=result.fallback_used,
        )


_service: ChatService | None = None


def get_chat_service() -> ChatService:
    """Return the process-wide chat service, creating it on first use."""
    global _service  # noqa: PLW0603
    if _service is None:
        config = load_model_roster().get(CHAT_MODEL_KEY)
        router = ModelRouter(
            llm_client=create_llm_client(),
            breaker_registry=CircuitBreakerRegistry(),
            queue_registry=QueueRegistry(),
            retry_config=RetryConfig(max_retries=2, base_delay=0.5),
        )
        _service = ChatService(router=router, model_config=config)
    return _service


def reset_chat_service() -> None:
    """Drop the cached service (used by tests and configuration reloads)."""
    global _service  # noqa: PLW0603
    _service = None
