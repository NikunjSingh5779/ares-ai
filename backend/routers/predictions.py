"""Predictions API router — ML-powered market forecasting endpoints.

Provides endpoints for Kronos model-based OHLCV predictions,
web data collection, and enhanced market research.

These endpoints supplement the main trading pipeline with ML-based
forecasting and data collection capabilities.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["predictions"])


@router.post("/predict/kronos")
async def kronos_predict(
    symbol: str = "BTC-USD",
    interval: str = "1d",
    lookback: int = 400,
    pred_len: int = 24,
) -> dict[str, Any]:
    """Run Kronos model-based OHLCV price prediction.

    Uses the Kronos foundation model (trained on 45+ global exchanges)
    to predict future price movements from historical data.

    Args:
        symbol: Trading symbol (e.g., BTC-USD, AAPL).
        interval: Candle interval (1d, 1h, 4h, etc.).
        lookback: Number of historical candles to use (max 512).
        pred_len: Number of candles to predict forward (max 120).

    Returns:
        Prediction result with direction, confidence, and forecasted prices.
    """
    from agents.kronos_predictor import KronosPredictorAgent, KronosPredictorInput
    from backend.data.ingestor import MarketDataIngestor
    from backend.data.repository import MarketDataRepository
    from database.connection import async_session_factory

    try:
        ingestor = MarketDataIngestor(
            repository=MarketDataRepository(session_factory=async_session_factory)
        )
        agent = KronosPredictorAgent(ingestor=ingestor)

        result = await agent.run(
            KronosPredictorInput(
                symbol=symbol,
                interval=interval,
                lookback=lookback,
                pred_len=pred_len,
            )
        )

        # Convert to dict for response
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return dict(result)

    except Exception as e:
        logger.error(f"Kronos prediction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")


@router.post("/collect/web-data")
async def collect_web_data(
    task: str = "Extract current AAPL stock price from Yahoo Finance",
    url: str | None = None,
    headless: bool = True,
) -> dict[str, Any]:
    """Collect data from the web using browser automation.

    Uses browser-use to navigate websites and extract financial data.
    Falls back to a descriptive message if browser-use is not installed.

    Args:
        task: Description of the data collection task.
        url: Optional starting URL.
        headless: Run browser in headless mode.

    Returns:
        Collected data with success status.
    """
    from agents.web_collector import WebCollectorAgent, WebCollectorInput

    try:
        agent = WebCollectorAgent()
        result = await agent.run(
            WebCollectorInput(
                task=task,
                url=url,
                headless=headless,
            )
        )

        if hasattr(result, "model_dump"):
            return result.model_dump()
        return dict(result)

    except Exception as e:
        logger.error(f"Web data collection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Web collection failed: {e}")


@router.get("/research/market-context")
async def market_context(
    symbol: str = "BTC-USD",
) -> dict[str, Any]:
    """Get comprehensive market context including web search results.

    Searches the web for recent news, company info, and macro context
    related to the specified symbol. Complements the main pipeline with
    fundamental research data.

    Args:
        symbol: Trading symbol (e.g., BTC-USD, AAPL).

    Returns:
        News, company info, and macro context from web search.
    """
    from backend.data.sources.web_search import get_web_search_provider

    try:
        provider = get_web_search_provider()
        context = await provider.search_market_context(symbol)
        return context

    except Exception as e:
        logger.error(f"Market context search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Market context failed: {e}")


@router.post("/research/web-search")
async def web_search(
    query: str,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """General-purpose web search for financial research.

    Args:
        query: Search query.
        max_results: Maximum results to return.

    Returns:
        List of search results with title, url, and snippet.
    """
    from backend.data.sources.web_search import get_web_search_provider

    try:
        provider = get_web_search_provider()
        results = await provider.searcher.search(query, max_results=max_results)
        return [r.to_dict() for r in results]

    except Exception as e:
        logger.error(f"Web search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Web search failed: {e}")
