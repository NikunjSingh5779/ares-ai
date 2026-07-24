"""News Agent — aggregates news and scores sentiment.

Implements the CLAUDE.md AGENT I/O CONTRACTS:
- Typed input/output schemas (Pydantic)
- Output validated on receipt
- rationale/explanation fields required for trading-relevant numbers
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError

from agents.base import AgentContext, BaseAgent
from agents.router import ModelRouter, RouterResult
from agents.state import NewsInput, NewsOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the News & Sentiment Analyst Agent in the ARES AI trading system.

Your role: Analyze the provided news headlines and market context, aggregate them,
and produce a structured sentiment analysis matching the schema below.

Rules:
1. Return ONLY valid JSON — no markdown, no explanation outside the JSON.
2. Your JSON must match this schema exactly:
   {
     "sentiment": <float from -1.0 (extremely bearish/fear) to +1.0 (extremely bullish/greed). 0.0 is neutral>,
     "key_events": ["list of max 5 most significant events/takeaways from the news"],
     "impact_scores": { "macro": 0.5, "symbol_specific": -0.2 },
     "sources": ["list of publishers/sources cited"],
     "rationale": "<string explaining your synthesis and how you derived the sentiment>"
   }
3. Deduplicate stories: if multiple headlines cover the same event, synthesize them into one key_event.
4. Separate signal from noise: ignore routine market recap headlines and focus on actual
   catalysts (earnings, macro data, policy changes, major corporate events).
5. If the headlines lack clear directional catalysts, default your sentiment closer to 0.0."""


class NewsAgent(BaseAgent[NewsInput, NewsOutput]):
    """Agent that fetches and analyzes news sentiment."""

    agent_name: str = "news"
    input_schema: type = NewsInput
    output_schema: type = NewsOutput

    def __init__(self, router: ModelRouter, context: AgentContext | None = None) -> None:
        """Initialize the News Agent."""
        super().__init__(context)
        self.router = router

    async def fetch_news(self, symbol: str, count: int = 10) -> list[dict[str, Any]]:
        """Fetch recent news for a symbol using Yahoo Finance."""
        base_symbol = symbol.split("-")[0] if "-" in symbol else symbol
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={base_symbol}&newsCount={count}"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                data = resp.json()
                return data.get("news", [])  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"Failed to fetch news for {symbol}: {e}")
            return []

    def build_prompt(self, symbol: str, news_items: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Build the messages for the LLM analysis call."""

        if not news_items:
            news_text = "No recent news found for this symbol."
        else:
            lines = []
            for item in news_items:
                title = item.get("title", "")
                publisher = item.get("publisher", "Unknown")
                lines.append(f"- [{publisher}] {title}")
            news_text = "\n".join(lines)

        content = f"""Target Symbol: {symbol}

Recent Headlines:
{news_text}

Analyze the above news items, synthesize the core events (deduplicating where needed),
and return your sentiment analysis as valid JSON matching the specified schema."""

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

    def _parse_llm_response(self, text: str) -> dict[str, Any]:
        """Parse LLM JSON response safely, falling back on error."""
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()

        try:
            data = json.loads(cleaned)
            return data  # type: ignore[no-any-return]
        except json.JSONDecodeError as e:
            logger.error(f"LLM JSON parse FAILED: {e}. Raw output: {text[:500]}")

            # Try to salvage with regex if possible
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                    logger.warning("Recovered JSON via regex extraction")
                    return data  # type: ignore[no-any-return]
                except json.JSONDecodeError:
                    pass

            logger.error("Falling back to neutral news sentiment due to JSON parse failure.")
            return {
                "sentiment": 0.0,
                "key_events": ["Error: Could not parse LLM analysis"],
                "impact_scores": {},
                "sources": [],
                "rationale": "LLM failed to return valid JSON.",
            }

    async def process(self, inputs: NewsInput) -> NewsOutput:
        """Execute the news agent logic."""
        logger.info(f"Running NewsAgent for {inputs.symbol}")

        # 1. Fetch News
        news_items = await self.fetch_news(inputs.symbol, count=15)

        if not news_items:
            # Fast-path fallback if no news is available
            return NewsOutput(
                sentiment=0.0,
                key_events=["No recent news found"],
                impact_scores={},
                sources=[],
                rationale="No news was returned by the provider.",
            )

        # 2. Build prompt
        messages = self.build_prompt(inputs.symbol, news_items)

        # 3. Call LLM via router
        try:
            # Get model chain from context
            model_chain = self.context.model_preferences.get("model_chain", [])
            if not model_chain:
                model_chain = ["open_router/openrouter/free"]

            # We want temperature 0.1 for consistent sentiment scoring (as per sentiment-analysis skill)
            result: RouterResult = await self.router.execute(
                model_chain=model_chain, messages=messages, temperature=0.1, max_tokens=500, rpm=20
            )

            if not result.success:
                logger.error(f"Router failed to get successful response. Errors: {result.errors}")
                return NewsOutput(
                    sentiment=0.0,
                    key_events=["Error: Router failed"],
                    impact_scores={},
                    sources=[],
                    rationale="LLM router failed.",
                )

            # Extract content from OpenAI-style response
            try:
                response_text = result.response["choices"][0]["message"]["content"]  # type: ignore[index]
            except (KeyError, IndexError, TypeError):
                response_text = ""

            if not response_text:
                return NewsOutput(
                    sentiment=0.0,
                    key_events=["Error: Empty response"],
                    impact_scores={},
                    sources=[],
                    rationale="Empty response from LLM.",
                )

            # 4. Parse & Validate
            parsed_data = self._parse_llm_response(response_text)

            # Ensure safe defaults for sources if LLM hallucinations happen
            if "sources" not in parsed_data or not isinstance(parsed_data["sources"], list):
                # Auto-fill from actual data
                parsed_data["sources"] = list(set([item.get("publisher", "Unknown") for item in news_items]))

            return NewsOutput(**parsed_data)

        except ValidationError as ve:
            logger.error(f"NewsOutput validation failed: {ve}")
            return NewsOutput(
                sentiment=0.0, key_events=[], impact_scores={}, sources=[], rationale=f"Validation error: {ve}"
            )
        except Exception as e:
            logger.error(f"NewsAgent execution failed: {e}")
            return NewsOutput(
                sentiment=0.0, key_events=[], impact_scores={}, sources=[], rationale=f"Execution error: {e}"
            )
