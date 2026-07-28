"""Web Data Collector Agent — browser-use powered web automation.

Collects financial data from websites using the browser-use library
for browser automation. Handles data extraction tasks that require
JavaScript rendering, multi-page navigation, or login-based access.

This agent is OPTIONAL — it gracefully degrades when browser-use
or Playwright is not installed.

Pattern inspired by the browser-use open-source library for AI-powered
browser automation.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from agents.base import AgentContext, BaseAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input/Output schemas
# ---------------------------------------------------------------------------


class WebCollectorInput(BaseModel):
    """Input for the Web Data Collector Agent."""

    task: str = Field(..., description="Navigation or data collection task")
    url: str | None = Field(default=None, description="Starting URL (optional, agent can navigate from search)")
    max_steps: int = Field(default=30, ge=5, le=100, description="Max browser interaction steps")
    headless: bool = Field(default=True, description="Run browser in headless mode")


class WebCollectorOutput(BaseModel):
    """Output from the Web Data Collector Agent."""

    success: bool = Field(default=False, description="Whether collection succeeded")
    data: list[dict[str, Any]] = Field(default_factory=list, description="Collected data items")
    text: str = Field(default="", description="Extracted text content")
    error: str | None = Field(default=None, description="Error message if collection failed")
    model_used: str = Field(default="", description="Browser automation backend used")
    steps_taken: int = Field(default=0, description="Number of steps taken")
    rationale: str = Field(default="", description="Summary of what was collected")


# ---------------------------------------------------------------------------
# Web Collector Agent
# ---------------------------------------------------------------------------

class WebCollectorAgent(BaseAgent[WebCollectorInput, WebCollectorOutput]):
    """Agent for web data collection using browser automation.

    Uses browser-use library to navigate websites, extract data,
    and collect financial information. Falls back gracefully when
    browser-use is not installed.

    Usage:
        agent = WebCollectorAgent()
        result = await agent.run(WebCollectorInput(
            task="Extract current AAPL stock price and PE ratio",
            url="https://finance.yahoo.com/quote/AAPL/",
        ))
    """

    agent_name: str = "web_collector"
    input_schema: type[BaseModel] = WebCollectorInput
    output_schema: type[BaseModel] = WebCollectorOutput

    def __init__(self, context: AgentContext | None = None) -> None:
        super().__init__(context=context)

    async def process(self, inputs: WebCollectorInput) -> dict[str, Any]:  # type: ignore[override]
        """Execute web data collection task."""
        # Try browser-use first
        result = await self._collect_with_browser_use(inputs)
        if result is not None:
            return result

        # Fallback: return helpful message about installation
        return {
            "success": False,
            "data": [],
            "text": "",
            "error": (
                "browser-use not available. To install, run:\n"
                "  pip install browser-use playwright\n"
                "  playwright install\n"
                "Or use a simpler HTTP-based data source instead."
            ),
            "model_used": "none",
            "steps_taken": 0,
            "rationale": "Web collection skipped: browser-use not installed.",
        }

    async def _collect_with_browser_use(
        self,
        inputs: WebCollectorInput,
    ) -> dict[str, Any] | None:
        """Attempt data collection using browser-use."""
        try:
            from browser_use import Agent as BrowserAgent  # optional dep, guarded by try/except
            from langchain_openai import ChatOpenAI

            # Try to use available LLM via OpenRouter-compatible endpoint
            llm = None
            try:
                from configs.settings import settings

                if settings.openrouter_api_key:
                    llm = ChatOpenAI(
                        model="openai/gpt-4o-mini",
                        openai_api_key=settings.openrouter_api_key,
                        openai_api_base=settings.openrouter_base_url,
                        temperature=0.1,
                    )
                elif settings.gemini_api_key:
                    llm = ChatOpenAI(
                        model="gemini/gemini-2.0-flash",
                        openai_api_key=settings.gemini_api_key,
                        openai_api_base=settings.gemini_base_url,
                        temperature=0.1,
                    )
            except Exception:
                logger.debug("Failed to configure LLM for browser-use", exc_info=True)

            if llm is None:
                logger.error(
                    "browser-use requires an LLM API key (OpenRouter or Gemini). "
                    "Set OPENROUTER_API_KEY or GEMINI_API_KEY in .env"
                )
                return {
                    "success": False,
                    "data": [],
                    "text": "",
                    "error": "browser-use needs an LLM API key (OPENROUTER_API_KEY or GEMINI_API_KEY)",
                    "model_used": "none",
                    "steps_taken": 0,
                    "rationale": "No LLM configured for browser-use agent.",
                }

            # Create the browser agent
            # NB: browser_use.Agent is a generic class; mypy cannot fully infer
            # the type parameters inside the guarded import block, so annotate
            # explicitly with Any to satisfy `mypy --strict` `var-annotated`.
            agent: Any = BrowserAgent(
                task=inputs.task,
                llm=llm,
                use_vision=False,
                max_actions_per_step=5,
            )

            # Run the agent
            history = await agent.run(max_steps=inputs.max_steps)

            # Extract results
            all_text = []
            all_data: list[Any] = []
            steps = 0

            # AgentHistoryList.history is the actual list[AgentHistory];
            # iterating AgentHistoryList directly would yield pydantic
            # (field-name, field-value) tuples (BaseModel.__iter__),
            # so use `.history` to get the AgentHistory items.
            if history:
                steps = len(history)  # AgentHistoryList defines __len__
                for step in history.history:
                    if hasattr(step, "result") and step.result:
                        result = step.result
                        all_text.append(str(result))

            return {
                "success": True,
                "data": all_data,
                "text": "\n".join(all_text[-5:]) if all_text else "Task completed.",
                "error": None,
                "model_used": "browser-use",
                "steps_taken": steps,
                "rationale": f"Browser-use completed task in {steps} steps.",
            }

        except ImportError as e:
            logger.debug(f"browser-use import failed: {e}")
            return None

        except Exception as e:
            logger.error(f"browser-use execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "data": [],
                "text": "",
                "error": f"browser-use error: {e}",
                "model_used": "browser-use",
                "steps_taken": 0,
                "rationale": f"browser-use failed: {e}",
            }


# ---------------------------------------------------------------------------
# Simplified HTTP-based data collector (no browser needed)
# ---------------------------------------------------------------------------

class SimpleDataCollector:
    """Lightweight HTTP-based data collector for simple scraping tasks.

    Does not require browser-use or Playwright. Suitable for extracting
    data from simple HTML pages and JSON APIs.
    """

    def __init__(self) -> None:
        self._client: Any = None

    async def fetch_json(self, url: str) -> dict[str, Any] | list[Any] | None:
        """Fetch and parse JSON from a URL."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                return resp.json()  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"JSON fetch failed for {url}: {e}")
            return None

    async def fetch_html(self, url: str) -> str | None:
        """Fetch HTML content from a URL."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                return resp.text
        except Exception as e:
            logger.error(f"HTML fetch failed for {url}: {e}")
            return None
