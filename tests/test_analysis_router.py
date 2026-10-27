"""Tests for the analysis API router, including the SSE streaming endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from agents.state import AgentState, PipelineStatus
from agents.supervisor import AnalysisDeadlineExceededError, Supervisor
from backend.core.metrics import get_metrics_snapshot
from backend.routers import analysis as analysis_module
from backend.services.analysis_control import (
    get_analysis_gate,
    get_analysis_state_store,
    reset_analysis_control,
)
from configs.settings import settings


@pytest.fixture(autouse=True)
def _reset_control() -> Iterator[None]:
    """Keep the process-wide gate and store isolated between tests."""
    reset_analysis_control()
    yield
    reset_analysis_control()


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


def _state(session_id: str, symbol: str = "BTC-USD", request: str = "Analyze") -> AgentState:
    return AgentState(
        symbol=symbol,
        request=request,
        request_id=f"req-{session_id}",
        session_id=session_id,
        pipeline_status=PipelineStatus(current_node="supervisor"),
    )


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


class _FakeSupervisor:
    """Minimal supervisor seam for the analysis routes."""

    def __init__(
        self,
        events: list[AgentState] | None = None,
        delay: float = 0.0,
        error: BaseException | None = None,
    ) -> None:
        self.events = events or []
        self.delay = delay
        self.error = error
        self.started = asyncio.Event()

    async def stream_analysis(
        self,
        symbol: str,
        request: str,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[AgentState]:
        self.started.set()
        if self.error is not None:
            raise self.error
        if self.delay:
            await asyncio.sleep(self.delay)
        for event in self.events:
            yield event

    async def run_analysis(
        self,
        symbol: str,
        request: str,
        timeout_seconds: float | None = None,
    ) -> AgentState:
        self.started.set()
        if self.error is not None:
            raise self.error
        if self.delay:
            await asyncio.sleep(self.delay)
        return _state("sync-result", symbol=symbol, request=request)


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

        fake_gen = _make_fake_stream_events(3)

        # We need to mock _get_supervisor to return a supervisor
        # whose stream_analysis yields our fake events
        mock_supervisor = AsyncMock(spec=Supervisor)
        mock_supervisor.stream_analysis = lambda symbol, request, timeout_seconds=None: fake_gen

        with patch("backend.routers.analysis._get_supervisor", return_value=mock_supervisor):
            # Use StreamingResponse directly
            from backend.routers.analysis import analyze_stream

            response = await analyze_stream(symbol="BTC-USD", x_analysis_prompt="test")
            assert response is not None

            # Collect events from the streaming response
            events = []
            async for chunk in response.body_iterator:
                events.append(chunk)

            # Should have at least some content
            assert len(events) > 0
            # Each event should be SSE-formatted (data: {...}\n\n)
            has_data_prefix = any("data: " in chunk for chunk in events)
            assert has_data_prefix, "Expected SSE data: prefix in stream output"
            assert get_analysis_gate().in_use == 0

    def test_stream_with_testclient(self, client: TestClient) -> None:
        """SSE endpoint returns 200 with text/event-stream content type."""
        # Mock the supervisor to avoid real pipeline execution
        from agents.supervisor import Supervisor

        fake_gen = _make_fake_stream_events(2)

        mock_supervisor = AsyncMock(spec=Supervisor)
        mock_supervisor.stream_analysis = lambda symbol, request, timeout_seconds=None: fake_gen

        with patch("backend.routers.analysis._get_supervisor", return_value=mock_supervisor):
            response = client.get("/api/v1/analyze/stream?symbol=BTC-USD&request=test")
            assert response.status_code == 200
            assert response.headers.get("content-type", "").startswith("text/event-stream")

    @pytest.mark.asyncio
    async def test_unstarted_stream_releases_its_lease(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A body iterator that is never started cannot leak the gate slot."""
        from backend.routers.analysis import analyze_stream

        fake = _FakeSupervisor(events=[_state("one")])
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)
        before = REGISTRY.get_sample_value("ares_analysis_runs_total", {"status": "cancelled"}) or 0.0

        response = await analyze_stream(symbol="BTC-USD", x_analysis_prompt="test")
        assert get_analysis_gate().in_use == 1
        stored = get_analysis_state_store().latest()
        assert stored is not None
        session_id = stored.session_id

        streaming = cast(analysis_module._AnalysisStreamingResponse, response)
        await streaming.aclose()
        await streaming.aclose()

        assert get_analysis_gate().in_use == 0
        stored = get_analysis_state_store().get(session_id)
        assert stored is not None
        assert stored.pipeline_status.end_time is not None
        assert "pipeline" in stored.pipeline_status.failed_nodes
        assert any("closed before start" in error["error"] for error in stored.errors)
        after = REGISTRY.get_sample_value("ares_analysis_runs_total", {"status": "cancelled"}) or 0.0
        assert after == before + 1


class TestAnalyzeControl:
    """POST /analyze uses the bounded gate and per-session store."""

    def test_route_returns_202_with_a_session_id(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeSupervisor(events=[])
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)

        response = client.post("/api/v1/analyze", json={"symbol": "BTC-USD"})

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "accepted"
        assert body["session_id"]

    @pytest.mark.asyncio
    async def test_cancelled_before_start_releases_its_lease(self) -> None:
        """A task cancelled before its first step must not leak the slot."""
        from backend.routers.analysis import _new_state, _schedule_background

        gate = get_analysis_gate()
        lease = await gate.try_start()
        store = get_analysis_state_store()
        state = _new_state("BTC-USD", "Analyze")
        store.put(state, make_latest=True)
        started = asyncio.Event()
        before = REGISTRY.get_sample_value("ares_analysis_runs_total", {"status": "cancelled"}) or 0.0

        async def never_runs() -> None:
            started.set()

        task = _schedule_background(never_runs(), lease, state.session_id)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

        assert not started.is_set()
        assert gate.in_use == 0
        stored = store.get(state.session_id)
        assert stored is not None
        assert any("cancelled before start" in error["error"] for error in stored.errors)
        after = REGISTRY.get_sample_value("ares_analysis_runs_total", {"status": "cancelled"}) or 0.0
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_returns_429_when_gate_is_full(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import analyze

        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: _FakeSupervisor())
        gate = get_analysis_gate()
        lease = await gate.try_start()
        try:
            with pytest.raises(HTTPException) as exc_info:
                await analyze({"symbol": "BTC-USD"})
        finally:
            lease.release()

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers == {"Retry-After": "1"}

    @pytest.mark.asyncio
    async def test_returns_429_when_budget_is_exhausted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import analyze

        monkeypatch.setattr(settings, "analysis_max_runs_per_hour", 1)
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: _FakeSupervisor())
        reset_analysis_control()
        gate = get_analysis_gate()
        lease = await gate.try_start()
        lease.release()

        with pytest.raises(HTTPException) as exc_info:
            await analyze({"symbol": "BTC-USD"})

        assert exc_info.value.status_code == 429
        assert "budget" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_rejects_null_symbol(self) -> None:
        from backend.routers.analysis import analyze

        with pytest.raises(HTTPException) as exc_info:
            await analyze({"symbol": None})

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_setup_failure_does_not_consume_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import analyze

        def _boom() -> Supervisor:
            raise RuntimeError("roster unavailable")

        monkeypatch.setattr("backend.routers.analysis._get_supervisor", _boom)
        gate = get_analysis_gate()
        before = gate.budget_remaining

        with pytest.raises(HTTPException) as exc_info:
            await analyze({"symbol": "BTC-USD"})

        assert exc_info.value.status_code == 500
        assert gate.budget_remaining == before

    @pytest.mark.asyncio
    async def test_installs_state_under_returned_session_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import analyze

        fake = _FakeSupervisor(events=[_state("supervisor-internal")])
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)

        response = await analyze({"symbol": "BTC-USD", "request": "Analyze"})
        session_id = response["session_id"]
        assert response["status"] == "accepted"

        # The placeholder is installed before the background task runs, so the
        # dashboard can immediately poll the new run instead of the old one.
        stored = get_analysis_state_store().get(session_id)
        assert stored is not None
        assert stored.symbol == "BTC-USD"

        await asyncio.gather(*analysis_module._background_tasks)

        stored = get_analysis_state_store().get(session_id)
        assert stored is not None
        assert stored.session_id == session_id
        assert stored.request == "Analyze"
        assert get_analysis_gate().in_use == 0

    @pytest.mark.asyncio
    async def test_completed_run_is_counted_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import analyze

        fake = _FakeSupervisor(events=[])
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)
        before = get_metrics_snapshot()["analysis_runs_total"]

        await analyze({"symbol": "BTC-USD"})
        await asyncio.gather(*analysis_module._background_tasks)

        assert get_metrics_snapshot()["analysis_runs_total"] == before + 1

    @pytest.mark.asyncio
    async def test_busy_rejection_is_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import analyze

        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: _FakeSupervisor())
        gate = get_analysis_gate()
        lease = await gate.try_start()
        before = REGISTRY.get_sample_value("ares_analysis_runs_total", {"status": "rejected_busy"}) or 0.0
        try:
            with pytest.raises(HTTPException):
                await analyze({"symbol": "BTC-USD"})
        finally:
            lease.release()

        after = REGISTRY.get_sample_value("ares_analysis_runs_total", {"status": "rejected_busy"}) or 0.0
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_background_timeout_marks_terminal_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import _background_analysis, _new_state

        monkeypatch.setattr(settings, "analysis_timeout_seconds", 0.02)
        reset_analysis_control()
        gate = get_analysis_gate()
        store = get_analysis_state_store()
        state = _new_state("BTC-USD", "Analyze")
        store.put(state, make_latest=True)
        lease = await gate.try_start()

        fake = _FakeSupervisor(error=AnalysisDeadlineExceededError("deadline"))
        await _background_analysis(
            cast(Supervisor, fake),
            "BTC-USD",
            "Analyze",
            state.session_id,
            lease,
            gate.timeout_seconds,
        )

        stored = store.get(state.session_id)
        assert stored is not None
        assert stored.pipeline_status.current_node == ""
        assert stored.pipeline_status.end_time is not None
        assert "pipeline" in stored.pipeline_status.failed_nodes
        assert any("timed out" in error["error"] for error in stored.errors)
        assert gate.in_use == 0

    @pytest.mark.asyncio
    async def test_background_plain_timeout_is_a_failure_not_a_deadline(self) -> None:
        """A DB/logging TimeoutError must not be reported as a run timeout."""
        from backend.routers.analysis import _background_analysis, _new_state

        reset_analysis_control()
        gate = get_analysis_gate()
        store = get_analysis_state_store()
        state = _new_state("BTC-USD", "Analyze")
        store.put(state, make_latest=True)
        lease = await gate.try_start()

        fake = _FakeSupervisor(error=TimeoutError("pool acquire timed out"))
        await _background_analysis(
            cast(Supervisor, fake),
            "BTC-USD",
            "Analyze",
            state.session_id,
            lease,
            gate.timeout_seconds,
        )

        stored = store.get(state.session_id)
        assert stored is not None
        assert any("pool acquire timed out" in error["error"] for error in stored.errors)
        assert not any("timed out after" in error["error"] for error in stored.errors)
        assert gate.in_use == 0

    @pytest.mark.asyncio
    async def test_background_cancellation_marks_terminal_state(self) -> None:
        from backend.routers.analysis import _background_analysis, _new_state

        reset_analysis_control()
        gate = get_analysis_gate()
        store = get_analysis_state_store()
        state = _new_state("BTC-USD", "Analyze")
        store.put(state, make_latest=True)
        lease = await gate.try_start()

        fake = _FakeSupervisor(delay=10.0)
        task = asyncio.create_task(
            _background_analysis(
                cast(Supervisor, fake),
                "BTC-USD",
                "Analyze",
                state.session_id,
                lease,
                gate.timeout_seconds,
            )
        )
        await fake.started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        stored = store.get(state.session_id)
        assert stored is not None
        assert any("cancelled" in error["error"] for error in stored.errors)
        assert gate.in_use == 0

    @pytest.mark.asyncio
    async def test_stream_releases_the_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import analyze_stream

        fake = _FakeSupervisor(events=[_state("one"), _state("two")])
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)

        response = await analyze_stream(symbol="BTC-USD", x_analysis_prompt="test")
        chunks = [chunk async for chunk in response.body_iterator]

        assert len(chunks) == 2
        assert get_analysis_gate().in_use == 0
        stored = get_analysis_state_store().latest()
        assert stored is not None
        assert stored.symbol == "BTC-USD"


class TestSignalControl:
    """POST /signal shares the gate and enforces the stage deadline."""

    @pytest.mark.asyncio
    async def test_returns_429_when_gate_is_full(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import signal

        monkeypatch.setattr(settings, "analysis_queue_timeout_seconds", 0.01)
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: _FakeSupervisor())
        reset_analysis_control()
        gate = get_analysis_gate()
        lease = await gate.try_start()
        try:
            with pytest.raises(HTTPException) as exc_info:
                await signal({"symbol": "BTC-USD"})
        finally:
            lease.release()

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_returns_504_on_deadline_and_releases_slot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import signal

        monkeypatch.setattr(settings, "analysis_timeout_seconds", 0.02)
        reset_analysis_control()
        fake = _FakeSupervisor(error=AnalysisDeadlineExceededError("deadline"))
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)

        with pytest.raises(HTTPException) as exc_info:
            await signal({"symbol": "BTC-USD"})

        assert exc_info.value.status_code == 504
        assert get_analysis_gate().in_use == 0
        stored = get_analysis_state_store().latest()
        assert stored is not None
        assert "pipeline" in stored.pipeline_status.failed_nodes

    @pytest.mark.asyncio
    async def test_plain_timeout_is_500_not_504(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A post-fill logging/DB TimeoutError must not invite a duplicate retry."""
        from backend.routers.analysis import signal

        reset_analysis_control()
        fake = _FakeSupervisor(error=TimeoutError("pool acquire timed out"))
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)

        with pytest.raises(HTTPException) as exc_info:
            await signal({"symbol": "BTC-USD"})

        assert exc_info.value.status_code == 500
        assert get_analysis_gate().in_use == 0
        stored = get_analysis_state_store().latest()
        assert stored is not None
        assert any("pool acquire timed out" in error["error"] for error in stored.errors)

    @pytest.mark.asyncio
    async def test_generic_failure_is_500_and_marks_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import signal

        reset_analysis_control()
        fake = _FakeSupervisor(error=RuntimeError("broker rejected"))
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)

        with pytest.raises(HTTPException) as exc_info:
            await signal({"symbol": "BTC-USD"})

        assert exc_info.value.status_code == 500
        assert get_analysis_gate().in_use == 0
        stored = get_analysis_state_store().latest()
        assert stored is not None
        assert stored.pipeline_status.end_time is not None
        assert any("broker rejected" in error["error"] for error in stored.errors)

    @pytest.mark.asyncio
    async def test_cancellation_marks_terminal_and_releases_slot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import signal

        reset_analysis_control()
        fake = _FakeSupervisor(delay=10.0)
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)

        task = asyncio.create_task(signal({"symbol": "BTC-USD"}))
        await fake.started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert get_analysis_gate().in_use == 0
        stored = get_analysis_state_store().latest()
        assert stored is not None
        assert any("cancelled" in error["error"].lower() for error in stored.errors)

    @pytest.mark.asyncio
    async def test_success_keeps_the_started_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.routers.analysis import signal

        fake = _FakeSupervisor(events=[])
        monkeypatch.setattr("backend.routers.analysis._get_supervisor", lambda: fake)

        result = await signal({"symbol": "BTC-USD"})

        assert result["status"] == "ok"
        stored = get_analysis_state_store().latest()
        assert stored is not None
        assert stored.symbol == "BTC-USD"
        assert stored.pipeline_status.end_time is not None
        assert get_analysis_gate().in_use == 0


class TestAgentStatusSessionLookup:
    """GET /agents/status can read a specific session instead of the latest."""

    @pytest.mark.asyncio
    async def test_reads_a_specific_session(self) -> None:
        from backend.routers.agents import agent_status

        store = get_analysis_state_store()
        store.put(_state("first"), make_latest=True)
        store.put(_state("second"), make_latest=True)

        first = await agent_status(session_id="first")
        latest = await agent_status()

        assert first["session_id"] == "first"
        assert latest["session_id"] == "second"
        assert first["has_run"] is True

    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self) -> None:
        from backend.routers.agents import agent_status

        with pytest.raises(HTTPException) as exc_info:
            await agent_status(session_id="missing")

        assert exc_info.value.status_code == 404
