"""Web Search Data Collector — financial news and market data via DuckDuckGo.

Provides web search capabilities for market research, news aggregation, and
fundamental data collection. Uses DuckDuckGo's search API (free, no API key
required) to fetch financial information.

Pattern from xai_finance_agent using DuckDuckGoTools integrated into
ARES's existing data pipeline structure.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 15  # seconds


# ---------------------------------------------------------------------------
# Search Result Model
# ---------------------------------------------------------------------------

class SearchResult:
    """A single web search result."""

    def __init__(
        self,
        title: str,
        url: str,
        snippet: str,
        source: str = "duckduckgo",
    ) -> None:
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# DuckDuckGo Web Search
# ---------------------------------------------------------------------------

class DuckDuckGoSearcher:
    """Financial web search via DuckDuckGo.

    Free, no API key required. Wraps the duckduckgo_search library
    (duckduckgo-search on PyPI) with a fallback to raw HTTP requests.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._use_library: bool | None = None  # None = not checked yet

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
        return self._client

    async def search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "wt-wt",  # Worldwide
    ) -> list[SearchResult]:
        """Search the web via DuckDuckGo.

        Args:
            query: Search query (e.g., "AAPL earnings Q4 2026").
            max_results: Maximum results to return.
            region: Region code (wt-wt = worldwide, us-en = US).

        Returns:
            List of SearchResult objects.
        """
        # Try library first (duckduckgo-search package)
        results = await self._search_library(query, max_results, region)
        if results:
            logger.debug(
                "DuckDuckGo search via library",
                extra={"query": query, "results": len(results)},
            )
            return results

        # Fallback: httpx-based scraping
        results = await self._search_httpx(query, max_results)
        if results:
            logger.debug(
                "DuckDuckGo search via httpx fallback",
                extra={"query": query, "results": len(results)},
            )
            return results

        logger.warning("DuckDuckGo search returned no results", extra={"query": query})
        return []

    async def _search_library(
        self,
        query: str,
        max_results: int = 10,
        region: str = "wt-wt",
    ) -> list[SearchResult]:
        """Search using the duckduckgo_search library."""
        if self._use_library is False:
            return []

        try:
            from duckduckgo_search import DDGS  # optional dep, guarded by try/except

            results: list[SearchResult] = []
            with DDGS() as ddgs:
                for i, r in enumerate(ddgs.text(query, region=region, max_results=max_results)):
                    if i >= max_results:
                        break
                    results.append(
                        SearchResult(
                            title=r.get("title", ""),
                            url=r.get("href", r.get("link", "")),
                            snippet=r.get("body", r.get("snippet", "")),
                            source="duckduckgo",
                        )
                    )
            self._use_library = True
            return results

        except ImportError:
            self._use_library = False
            logger.debug("duckduckgo_search library not installed, using httpx fallback")
            return []

        except Exception as e:
            self._use_library = False
            logger.warning(f"DuckDuckGo library search failed: {e}, using httpx fallback")
            return []

    async def _search_httpx(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Fallback search using direct HTTP requests to DuckDuckGo's HTML API."""
        try:
            client = await self._get_client()
            url = "https://html.duckduckgo.com/html/"
            params = {"q": query}

            resp = await client.post(url, data=params)
            resp.raise_for_status()

            # Parse HTML results (simple extraction)
            from html.parser import HTMLParser

            class DDGParser(HTMLParser):
                def __init__(self) -> None:
                    super().__init__()
                    self.results: list[SearchResult] = []
                    self._in_result = False
                    self._current: dict[str, str] = {}
                    self._tag_stack: list[str] = []

                def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                    self._tag_stack.append(tag)
                    attrs_dict = dict(attrs)
                    if tag == "a" and attrs_dict.get("class") == "result__a":
                        self._in_result = True
                        self._current = {"title": "", "url": str(attrs_dict.get("href", "") or ""), "snippet": ""}
                    elif tag == "a" and "result__snippet" in str(attrs_dict.get("class", "")):
                        self._current["snippet"] = ""

                def handle_data(self, data: str) -> None:
                    if self._in_result:
                        self._current["title"] += data

                def handle_endtag(self, tag: str) -> None:
                    if tag == "a" and self._in_result:
                        self._in_result = False
                        if self._current.get("title", "").strip():
                            self.results.append(
                                SearchResult(
                                    title=self._current.get("title", "").strip(),
                                    url=self._current.get("url", ""),
                                    snippet=self._current.get("snippet", "").strip(),
                                    source="duckduckgo",
                                )
                            )
                        self._current = {}
                    self._tag_stack.pop() if self._tag_stack else None

            parser = DDGParser()
            parser.feed(resp.text)
            return parser.results[:max_results]

        except Exception as e:
            logger.error(f"DuckDuckGo httpx fallback failed: {e}")
            return []

    async def search_financial_news(
        self,
        symbol: str,
        max_results: int = 5,
    ) -> list[dict[str, str]]:
        """Search for financial news about a specific symbol/ticker."""
        query = f"{symbol} stock market news"
        results = await self.search(query, max_results=max_results)
        return [r.to_dict() for r in results]

    async def search_company_info(
        self,
        company_name: str,
        max_results: int = 5,
    ) -> list[dict[str, str]]:
        """Search for company fundamentals and background."""
        query = f"{company_name} company overview financials"
        results = await self.search(query, max_results=max_results)
        return [r.to_dict() for r in results]

    async def search_macro_economic(
        self,
        topic: str,
        max_results: int = 5,
    ) -> list[dict[str, str]]:
        """Search for macroeconomic data or trends."""
        query = f"{topic} economic data 2026"
        results = await self.search(query, max_results=max_results)
        return [r.to_dict() for r in results]

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# ---------------------------------------------------------------------------
# WebSearchSource (composable with the existing data source registry)
# ---------------------------------------------------------------------------

class WebSearchProvider:
    """Web search provider integrated into ARES data pipeline.

    Provides search capabilities alongside the OHLCV data sources.
    Used by agents for fundamental research and news enhancement.
    """

    def __init__(self) -> None:
        self.searcher = DuckDuckGoSearcher()

    async def search_market_context(
        self,
        symbol: str,
        max_news: int = 5,
        max_company: int = 3,
    ) -> dict[str, Any]:
        """Comprehensive market context search for a symbol.

        Returns news, company info, and macro context in one call.
        """
        news = await self.searcher.search_financial_news(symbol, max_results=max_news)

        # Extract company name from symbol (simple heuristic)
        base = symbol.split("-")[0] if "-" in symbol else symbol.split(".")[0]
        company = await self.searcher.search_company_info(base, max_results=max_company)

        return {
            "symbol": symbol,
            "news": news,
            "company_info": company,
            "searched_at": datetime.utcnow().isoformat(),
            "sources_used": ["duckduckgo"],
        }

    async def close(self) -> None:
        await self.searcher.close()


# Singleton
_web_search_provider: WebSearchProvider | None = None


def get_web_search_provider() -> WebSearchProvider:
    """Get or create the web search provider singleton."""
    global _web_search_provider
    if _web_search_provider is None:
        _web_search_provider = WebSearchProvider()
    return _web_search_provider
