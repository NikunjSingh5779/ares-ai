import json
from unittest.mock import AsyncMock

import pytest

from agents.base import AgentContext
from agents.news import NewsAgent
from agents.router import RouterResult
from agents.state import NewsInput, NewsOutput


@pytest.fixture
def mock_context():
    return AgentContext(task_id="test", session_id="test")


@pytest.fixture
def mock_router():
    router = AsyncMock()
    return router


@pytest.fixture
def news_agent(mock_context, mock_router):
    return NewsAgent(context=mock_context, router=mock_router)


@pytest.mark.asyncio
async def test_news_agent_success(news_agent, mock_router):
    # Mock news fetching
    news_items = [
        {"title": "Fed cuts rates", "publisher": "Reuters"},
        {"title": "Tech stocks rally", "publisher": "Bloomberg"}
    ]
    news_agent.fetch_news = AsyncMock(return_value=news_items)

    # Mock LLM router response
    expected_json = {
        "sentiment": 0.8,
        "key_events": ["Fed cut rates by 50 bps", "Tech stocks rallied strongly"],
        "impact_scores": {"macro": 0.8, "tech_sector": 0.9},
        "sources": ["Reuters", "Bloomberg"],
        "rationale": "Very positive macro event."
    }
    router_result = RouterResult()
    router_result.success = True
    router_result.response = {
        "choices": [{"message": {"content": json.dumps(expected_json)}}]
    }
    mock_router.route.return_value = router_result

    result = await news_agent.process(NewsInput(symbol="BTC-USD"))

    assert isinstance(result, NewsOutput)
    assert result.sentiment == 0.8
    assert len(result.key_events) == 2
    assert "Reuters" in result.sources


@pytest.mark.asyncio
async def test_news_agent_json_fallback(news_agent, mock_router):
    news_agent.fetch_news = AsyncMock(return_value=[{"title": "Test", "publisher": "Test"}])

    # LLM returns invalid JSON
    router_result = RouterResult()
    router_result.success = True
    router_result.response = {
        "choices": [{"message": {"content": "I think the sentiment is positive but here's some text instead of JSON."}}]
    }
    mock_router.route.return_value = router_result

    result = await news_agent.process(NewsInput(symbol="BTC-USD"))

    assert isinstance(result, NewsOutput)
    assert result.sentiment == 0.0
    assert result.rationale == "LLM failed to return valid JSON."


@pytest.mark.asyncio
async def test_news_agent_no_news_fallback(news_agent, mock_router):
    news_agent.fetch_news = AsyncMock(return_value=[])

    result = await news_agent.process(NewsInput(symbol="BTC-USD"))

    # Should short-circuit without calling router
    mock_router.route.assert_not_called()
    assert isinstance(result, NewsOutput)
    assert result.sentiment == 0.0
    assert "No news" in result.rationale


def test_parse_llm_response_with_regex(news_agent):
    # Tests the regex fallback inside _parse_llm_response
    content = "Here is my JSON:\n```json\n{\"sentiment\": 0.5, \"key_events\": [], " \
        "\"impact_scores\": {}, \"sources\": [], \"rationale\": \"Ok\"}\n```\nSome other text."

    parsed = news_agent._parse_llm_response(content)
    assert parsed["sentiment"] == 0.5
    assert parsed["rationale"] == "Ok"
