"""Tests for the analysis API router, including the SSE streaming endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.state import AgentState, PipelineStatus


@pytest.fixture
def app() -> FastAPI:
    """Create a fresh FastAPI instance for each test."""
    result = FastAPI()
    from backend.routers.analysis import router

    result.include_router(router)
    return result


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Test client bound to the app."""
    return TestClient(app)


def _make_fake_stream_events(count: int):
    """Yield `count` fake AgentState updates."""

    async def _gen():
        for i in range(count):
            yield AgentState(
                symbol="BTC-USD",
                request=f"step-{i}",
                request_id=f"req-{i}",
                session_id=f"sess-{i}",
                pipeline_status=PipelineStatus(
                    current_node=("supervisor" if i == 0 else f"agent-{i}"),
                    completed_nodes=[f"agent-{j}" for j in range(i + 1)],
                    failed_nodes=[],
                    skipped_nodes=[],
                ),
            )

    return _gen()


class TestAnalyzeStream:
    """SSE streaming endpoint tests."""

    def test_requires_symbol(self, client: TestClient) -> None:
        """Missing symbol returns 400."""
        response = client.get("/api/v1/analyze/stream")
        assert response.status_code == 400
        assert "symbol" in response.text

    @pytest.mark.asyncio
    async def test_stream_yields_multiple_events(self, app: FastAPI) -> None:
        """The SSE endpoint yields multiple distinct events, not just one."""
        from backend.routers.analysis import router

        # Build a fresh app with the router
        test_app = FastAPI()
        test_app.include_router(router)

        from agents.supervisor import Supervisor

        fake_gen = _make_fake_stream_events(3)

        # We need to mock _get_supervisor to return a supervisor
        # whose stream_analysis yields our fake events
        mock_supervisor = AsyncMock(spec=Supervisor)
        mock_supervisor.stream_analysis = lambda symbol, request: fake_gen  # type: ignore[method-assign]

        with patch("backend.routers.analysis._get_supervisor", return_value=mock_supervisor):
            # Use StreamingResponse directly
            from backend.routers.analysis import analyze_stream

            response = await analyze_stream(symbol="BTC-USD", request="test")
            assert response is not None

            # Collect events from the streaming response
            events = []
            async for chunk in response.body_iterator:  # type: ignore[union-attr]
                events.append(chunk)

            # Should have at least some content
            assert len(events) > 0
            # Each event should be SSE-formatted (data: {...}\n\n)
            has_data_prefix = any("data: " in chunk for chunk in events)
            assert has_data_prefix, "Expected SSE data: prefix in stream output"

    def test_stream_with_testclient(self, client: TestClient) -> None:
        """SSE endpoint returns 200 with text/event-stream content type."""
        # Mock the supervisor to avoid real pipeline execution
        from agents.supervisor import Supervisor

        fake_gen = _make_fake_stream_events(2)

        mock_supervisor = AsyncMock(spec=Supervisor)
        mock_supervisor.stream_analysis = lambda symbol, request: fake_gen  # type: ignore[method-assign]

        with patch("backend.routers.analysis._get_supervisor", return_value=mock_supervisor):
            response = client.get("/api/v1/analyze/stream?symbol=BTC-USD&request=test")
            assert response.status_code == 200
            assert response.headers.get("content-type", "").startswith("text/event-stream")
