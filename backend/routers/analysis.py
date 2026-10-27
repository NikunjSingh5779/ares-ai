"""Analysis API router — market analysis and trading signals.

Endpoints:
    POST /api/v1/analyze     — Run the full Supervisor pipeline and return state
    POST /api/v1/signal      — Run the pipeline, return the execution result
    GET  /api/v1/analyze/stream — SSE stream of incremental pipeline state updates
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Coroutine
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from starlette.types import Receive, Scope, Send

from agents.circuit_breaker import CircuitBreakerRegistry
from agents.client import create_llm_client
from agents.log import AgentLogger
from agents.models import load_model_roster
from agents.queue import QueueRegistry
from agents.registry import AgentRegistry
from agents.retry import RetryConfig
from agents.router import ModelRouter
from agents.state import AgentState, PipelineStatus
from agents.supervisor import AnalysisDeadlineExceededError, Supervisor
from backend.core.metrics import record_analysis_run
from backend.services.analysis_control import (
    AnalysisBudgetExceededError,
    AnalysisBusyError,
    AnalysisLease,
    get_analysis_gate,
    get_analysis_state_store,
)
from backend.services.improvement_service import record_reflection_improvement
from database.connection import async_session_factory

router = APIRouter(prefix="/api/v1", tags=["trading"])

logger = logging.getLogger("ares.api.analysis")

# Strong references to accepted background runs so they are not garbage
# collected before they release their analysis lease.
_background_tasks: set[asyncio.Task[None]] = set()

# Lazy-initialised supervisor singleton — created on first call to _get_supervisor()
_supervisor: Supervisor | None = None


def _get_supervisor() -> Supervisor:
    """Get or create the cached Supervisor singleton.

    Creates all dependencies once on first call and caches them for the
    lifetime of the process.
    """
    global _supervisor  # noqa: PLW0603

    if _supervisor is not None:
        return _supervisor

    # 1. Load model roster from configs/models.yaml
    roster = load_model_roster()

    # 2. Shared infrastructure
    breaker_registry = CircuitBreakerRegistry()
    queue_registry = QueueRegistry()
    logger = AgentLogger()

    # 3. LLM client — use real API key if configured, otherwise fall back
    #    to a stub so local development doesn't crash
    llm_client = create_llm_client()

    # 4. Model router with retry chain
    router_model = ModelRouter(
        llm_client=llm_client,
        breaker_registry=breaker_registry,
        queue_registry=queue_registry,
        retry_config=RetryConfig(max_retries=2, base_delay=0.5),
    )

    # 5. Agent registry — register every pipeline agent
    registry = AgentRegistry(
        model_roster=roster,
        router=router_model,
        breaker_registry=breaker_registry,
        queue_registry=queue_registry,
    )

    from agents.execution import ExecutionAgent
    from agents.journal import JournalAgent
    from agents.kronos_predictor import KronosPredictorAgent
    from agents.market_analyst import MarketAnalystAgent
    from agents.memory import MemoryAgent
    from agents.news import NewsAgent
    from agents.quant import QuantAgent
    from agents.reflection import ReflectionAgent
    from agents.risk import RiskAgent
    from agents.web_collector import WebCollectorAgent
    from backend.data.ingestor import MarketDataIngestor
    from backend.data.repository import MarketDataRepository
    from backend.routers.live import _get_engine as get_live_engine
    from backend.routers.trading import get_paper_trading_ledger
    from database.connection import async_session_factory

    paper_ledger = get_paper_trading_ledger()
    shared_paper_engine = paper_ledger.engine
    live_engine = get_live_engine()
    shared_ingestor = MarketDataIngestor(repository=MarketDataRepository(session_factory=async_session_factory))

    registry.register("market_analyst", agent=MarketAnalystAgent(router=router_model, ingestor=shared_ingestor))
    registry.register("quant", agent=QuantAgent(router=router_model, ingestor=shared_ingestor))
    registry.register("risk", agent=RiskAgent(router=router_model, ingestor=shared_ingestor))
    registry.register(
        "execution",
        agent=ExecutionAgent(
            engine=shared_paper_engine,
            live_engine=live_engine,
            session_factory=async_session_factory,
            ledger=paper_ledger,
        ),
    )
    registry.register("journal", agent=JournalAgent(session_factory=async_session_factory))
    registry.register("reflection", agent=ReflectionAgent())
    registry.register("memory", agent=MemoryAgent())

    # Register Kronos predictor (ML-powered OHLCV forecasting)
    registry.register("kronos_predictor", agent=KronosPredictorAgent(ingestor=shared_ingestor))

    # Register web data collector (browser-use for scraping)
    registry.register("web_collector", agent=WebCollectorAgent())

    # Special cased / missing implementation
    registry.register("consensus")
    registry.register("vision")

    # Register news agent (now enhanced with web search fallback)
    registry.register("news", agent=NewsAgent(router=router_model))

    # 6. Supervisor
    supervisor = Supervisor(
        registry=registry,
        router=router_model,
        logger=logger,
        post_run_hook=record_reflection_improvement,
    )
    supervisor.build_graph()

    _supervisor = supervisor
    return _supervisor


@router.get("/signals/history")
async def signals_history(limit: int = 50) -> list[dict[str, Any]]:
    """Get historical signals."""
    query = text("""
        SELECT
            id, symbol, direction, confidence, composite_confidence,
            market_analyst_confidence, quant_confidence, news_sentiment,
            risk_score, risk_approved, is_consensus, rationale, is_executed,
            created_at, agent_outputs
        FROM signals
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    async with async_session_factory() as session:
        result = await session.execute(query, {"limit": limit})
        rows = result.fetchall()

    entries = []
    for row in rows:
        entries.append(
            {
                "id": str(row.id),
                "symbol": row.symbol,
                "direction": row.direction,
                "confidence": float(row.confidence) if row.confidence is not None else 0.0,
                "composite_confidence": float(row.composite_confidence)
                if row.composite_confidence is not None
                else 0.0,
                "market_analyst_confidence": float(row.market_analyst_confidence)
                if row.market_analyst_confidence is not None
                else 0.0,
                "quant_confidence": float(row.quant_confidence) if row.quant_confidence is not None else 0.0,
                "news_sentiment": float(row.news_sentiment) if row.news_sentiment is not None else 0.0,
                "risk_score": float(row.risk_score) if row.risk_score is not None else 0.0,
                "risk_approved": row.risk_approved,
                "is_consensus": row.is_consensus,
                "rationale": row.rationale,
                "is_executed": row.is_executed,
                "created_at": row.created_at.isoformat()
                if hasattr(row.created_at, "isoformat")
                else str(row.created_at),
                "agent_outputs": row.agent_outputs,
            }
        )

    return entries


def get_last_state() -> AgentState | None:
    """Return the most recently started analysis state."""
    return get_analysis_state_store().latest()


def get_state(session_id: str) -> AgentState | None:
    """Return one analysis state by session id, or ``None`` if evicted."""
    return get_analysis_state_store().get(session_id)


def _new_state(symbol: str, request_text: str) -> AgentState:
    """Build the placeholder state installed before a run starts."""
    return AgentState(
        symbol=symbol,
        request=request_text,
        request_type="analysis",
        request_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        pipeline_status=PipelineStatus(
            current_node="supervisor",
            completed_nodes=[],
            failed_nodes=[],
            skipped_nodes=[],
            start_time=datetime.now(UTC).isoformat(),
        ),
    )


def _symbol_from(body: dict[str, Any]) -> str:
    """Return a stripped symbol, rejecting non-string values such as null."""
    raw = body.get("symbol")
    return raw.strip() if isinstance(raw, str) else ""


def _request_from(body: dict[str, Any]) -> str:
    """Return a non-empty request string."""
    raw = body.get("request", "Analyze")
    return raw if isinstance(raw, str) and raw.strip() else "Analyze"


def _mark_terminal(session_id: str, message: str) -> None:
    """Record a timeout/failure/cancellation on a session without losing progress."""
    store = get_analysis_state_store()
    state = store.get(session_id)
    if state is None:
        return
    updated = state.model_copy(deep=True)
    updated.pipeline_status.current_node = ""
    updated.pipeline_status.end_time = datetime.now(UTC).isoformat()
    if "pipeline" not in updated.pipeline_status.failed_nodes:
        updated.pipeline_status.failed_nodes.append("pipeline")
    updated.errors.append({"agent": "pipeline", "error": message})
    store.put(updated)


def _mark_completed(session_id: str) -> None:
    """Set the end time on a run that completed normally."""
    store = get_analysis_state_store()
    state = store.get(session_id)
    if state is None:
        return
    updated = state.model_copy(deep=True)
    updated.pipeline_status.end_time = datetime.now(UTC).isoformat()
    store.put(updated)


def _rate_limit(exc: AnalysisBusyError | AnalysisBudgetExceededError) -> HTTPException:
    """Map a gate rejection to a fail-closed 429 with a retry hint."""
    status = "rejected_budget" if isinstance(exc, AnalysisBudgetExceededError) else "rejected_busy"
    record_analysis_run(status)
    return HTTPException(
        status_code=429,
        detail=str(exc),
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


def _schedule_background(
    coro: Coroutine[Any, Any, None],
    lease: AnalysisLease,
    session_id: str,
) -> asyncio.Task[None]:
    """Start an accepted analysis without tying its slot to the HTTP response.

    The done callback releases the lease even if the task is cancelled before
    its coroutine starts, which would skip the coroutine's own ``finally``.  A
    run that never started is also marked terminal so the dashboard does not
    show a permanently pending placeholder.
    """
    started = False

    async def _run() -> None:
        nonlocal started
        started = True
        await coro

    task = asyncio.create_task(_run())
    _background_tasks.add(task)

    def _on_done(done: asyncio.Task[None]) -> None:
        _background_tasks.discard(done)
        lease.release()
        if not started:
            coro.close()
            _mark_terminal(session_id, "Analysis cancelled before start")
            record_analysis_run("cancelled")

    task.add_done_callback(_on_done)
    return task


async def _background_analysis(
    supervisor: Supervisor,
    symbol: str,
    request_text: str,
    session_id: str,
    lease: AnalysisLease,
    timeout_seconds: float,
) -> None:
    """Run one accepted analysis under the deadline and release its slot."""
    store = get_analysis_state_store()
    status = "failed"
    try:
        async for state_update in supervisor.stream_analysis(
            symbol=symbol,
            request=request_text,
            timeout_seconds=timeout_seconds,
        ):
            # Keep the API-issued id so the caller can correlate the run
            # even though the supervisor creates its own internal state.
            state_update.session_id = session_id
            store.put(state_update)
        _mark_completed(session_id)
        status = "completed"
    except AnalysisDeadlineExceededError:
        status = "timeout"
        _mark_terminal(session_id, f"Analysis timed out after {timeout_seconds:.0f}s")
        logger.warning(
            "Background analysis timed out",
            extra={"symbol": symbol, "session_id": session_id},
        )
    except asyncio.CancelledError:
        status = "cancelled"
        _mark_terminal(session_id, "Analysis cancelled")
        raise
    except Exception as exc:
        status = "failed"
        _mark_terminal(session_id, str(exc))
        logger.exception(
            "Background analysis failed",
            extra={"symbol": symbol, "session_id": session_id},
        )
    finally:
        lease.release()
        record_analysis_run(status)


@router.post("/analyze", status_code=202)
async def analyze(body: dict[str, Any]) -> dict[str, Any]:
    """Run the full supervisor pipeline for a given symbol and request in the background.

    Returns HTTP 202 Accepted and streams updates to the state. The run is
    bounded by the process-wide analysis gate; a busy pipeline or an exhausted
    run budget returns 429 instead of queueing an unbounded task.
    """
    symbol = _symbol_from(body)
    request_text = _request_from(body)

    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    # Build the supervisor before consuming a run slot so a transient
    # configuration failure does not burn the hourly budget.
    try:
        supervisor = _get_supervisor()
    except Exception as exc:
        record_analysis_run("setup_failed")
        logger.exception("Supervisor setup failed", extra={"symbol": symbol})
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    gate = get_analysis_gate()
    try:
        lease = await gate.try_start()
    except (AnalysisBusyError, AnalysisBudgetExceededError) as exc:
        raise _rate_limit(exc) from exc

    try:
        state = _new_state(symbol, request_text)
        get_analysis_state_store().put(state, make_latest=True)
        _schedule_background(
            _background_analysis(
                supervisor,
                symbol,
                request_text,
                state.session_id,
                lease,
                gate.timeout_seconds,
            ),
            lease,
            state.session_id,
        )
        return {
            "status": "accepted",
            "message": "Analysis started in background",
            "session_id": state.session_id,
            "timeout_seconds": gate.timeout_seconds,
        }
    except Exception as exc:
        lease.release()
        record_analysis_run("failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class _TrackedStream:
    """Async iterator wrapper that records whether iteration actually began."""

    def __init__(self, content: AsyncIterator[str]) -> None:
        self._content = content
        self.started = False

    def __aiter__(self) -> _TrackedStream:
        return self

    async def __anext__(self) -> str:
        self.started = True
        return await self._content.__anext__()

    async def aclose(self) -> None:
        aclose = getattr(self._content, "aclose", None)
        if aclose is not None:
            await aclose()


class _AnalysisStreamingResponse(StreamingResponse):
    """SSE response that always releases its analysis lease.

    A ``StreamingResponse`` whose body iterator is never started cannot run the
    generator's ``finally`` block.  Releasing from the response closes that
    leak when a client disconnects before the first chunk, and a run that never
    started is marked terminal so the dashboard does not show a pending
    placeholder forever.
    """

    def __init__(
        self,
        content: AsyncIterator[str],
        lease: AnalysisLease,
        session_id: str,
        **kwargs: Any,
    ) -> None:
        tracked = _TrackedStream(content)
        super().__init__(tracked, **kwargs)
        self._tracked = tracked
        self._lease = lease
        self._session_id = session_id
        self._closed = False

    async def aclose(self) -> None:
        """Close the body iterator and release the slot exactly once."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._tracked.aclose()
        except Exception:
            logger.debug("Analysis stream close failed", exc_info=True)
        finally:
            self._lease.release()
            if not self._tracked.started:
                _mark_terminal(self._session_id, "Analysis stream closed before start")
                record_analysis_run("cancelled")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.aclose()


async def _stream_analysis_events(
    supervisor: Supervisor,
    symbol: str,
    request_text: str,
    session_id: str,
    lease: AnalysisLease,
    timeout_seconds: float,
):
    """Async generator yielding SSE-formatted pipeline state updates.

    The gate slot is released when the stream completes, times out, fails, or
    the response is closed.  A timeout is reported as one final SSE event so
    the client can distinguish it from a clean completion.  The supervisor's
    deadline is checked between stages, so a timeout never cancels an
    execution stage that may already have committed a fill.
    """
    store = get_analysis_state_store()
    status = "failed"
    terminal = False
    try:
        async for state_update in supervisor.stream_analysis(
            symbol=symbol,
            request=request_text,
            timeout_seconds=timeout_seconds,
        ):
            state_update.session_id = session_id
            store.put(state_update)
            data = json.dumps(_state_to_dict(state_update), default=str)
            yield f"data: {data}\n\n"
        _mark_completed(session_id)
        status = "completed"
        terminal = True
    except AnalysisDeadlineExceededError:
        status = "timeout"
        terminal = True
        _mark_terminal(session_id, f"Analysis timed out after {timeout_seconds:.0f}s")
        payload = json.dumps({"error": "timeout", "session_id": session_id}, default=str)
        yield f"data: {payload}\n\n"
    except asyncio.CancelledError:
        status = "cancelled"
        terminal = True
        _mark_terminal(session_id, "Analysis stream cancelled")
        raise
    except GeneratorExit:
        status = "cancelled"
        terminal = True
        _mark_terminal(session_id, "Analysis stream disconnected")
        raise
    except Exception as exc:
        status = "failed"
        terminal = True
        _mark_terminal(session_id, str(exc))
        logger.exception("Analysis stream failed", extra={"symbol": symbol, "session_id": session_id})
        payload = json.dumps({"error": "analysis_failed", "detail": str(exc), "session_id": session_id}, default=str)
        yield f"data: {payload}\n\n"
    finally:
        if not terminal:
            status = "cancelled"
        lease.release()
        record_analysis_run(status)


@router.get("/analyze/stream")
async def analyze_stream(
    symbol: str = "",
    x_analysis_prompt: str = Header(default="Analyze"),
) -> StreamingResponse:
    """Stream incremental pipeline state updates via Server-Sent Events.

    This endpoint runs the full Supervisor pipeline and pushes each
    incremental AgentState update to the client as a JSON-encoded SSE
    event as it happens, instead of requiring the client to poll.

    Query parameters:
        symbol: Ticker symbol to analyse (required).

    The analysis prompt defaults to ``"Analyze"`` and can be overridden
    via the ``X-Analysis-Prompt`` HTTP header.  Prompt text is accepted
    via header so it does not appear in server access logs.

    Returns:
        StreamingResponse with media_type text/event-stream.
    """
    if not symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")
    symbol = symbol.strip()

    # Build the supervisor before consuming a run slot so a transient
    # configuration failure does not burn the hourly budget.
    try:
        supervisor = _get_supervisor()
    except Exception as exc:
        record_analysis_run("setup_failed")
        logger.exception("Supervisor setup failed", extra={"symbol": symbol})
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    gate = get_analysis_gate()
    try:
        lease = await gate.try_start()
    except (AnalysisBusyError, AnalysisBudgetExceededError) as exc:
        raise _rate_limit(exc) from exc

    try:
        state = _new_state(symbol, x_analysis_prompt)
        get_analysis_state_store().put(state, make_latest=True)
        return _AnalysisStreamingResponse(
            _stream_analysis_events(
                supervisor,
                symbol,
                x_analysis_prompt,
                state.session_id,
                lease,
                gate.timeout_seconds,
            ),
            lease,
            state.session_id,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as exc:
        lease.release()
        record_analysis_run("failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/signal")
async def signal(body: dict[str, Any]) -> dict[str, Any]:
    """Run the pipeline synchronously and return the consolidated signal result.

    This bypasses background tasks for immediate response. It shares the same
    gate as ``/analyze``: a busy pipeline is rejected with 429 and a run that
    reaches the deadline before execution returns 504. The deadline is checked
    between stages, so it cannot cancel an execution stage after a fill was
    accepted.
    """
    symbol = _symbol_from(body)
    request_text = _request_from(body)

    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    # Build the supervisor before consuming a run slot so a transient
    # configuration failure does not burn the hourly budget.
    try:
        supervisor = _get_supervisor()
    except Exception as exc:
        record_analysis_run("setup_failed")
        logger.exception("Supervisor setup failed", extra={"symbol": symbol})
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    gate = get_analysis_gate()
    try:
        lease = await gate.acquire()
    except (AnalysisBusyError, AnalysisBudgetExceededError) as exc:
        raise _rate_limit(exc) from exc

    status = "failed"
    try:
        placeholder = _new_state(symbol, request_text)
        store = get_analysis_state_store()
        store.put(placeholder, make_latest=True)

        try:
            state = await supervisor.run_analysis(
                symbol=symbol,
                request=request_text,
                timeout_seconds=gate.timeout_seconds,
            )
        except AnalysisDeadlineExceededError as exc:
            status = "timeout"
            _mark_terminal(placeholder.session_id, f"Analysis timed out after {gate.timeout_seconds:.0f}s")
            raise HTTPException(
                status_code=504,
                detail=f"Analysis timed out after {gate.timeout_seconds:.0f}s",
            ) from exc
        except asyncio.CancelledError:
            status = "cancelled"
            _mark_terminal(placeholder.session_id, "Analysis cancelled")
            raise
        except Exception as exc:
            status = "failed"
            _mark_terminal(placeholder.session_id, str(exc))
            logger.exception(
                "Analysis signal failed",
                extra={"symbol": symbol, "session_id": placeholder.session_id},
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        state.session_id = placeholder.session_id
        state.pipeline_status.end_time = datetime.now(UTC).isoformat()
        store.put(state)
        status = "completed"

        # We must convert to dict because previous logic expected state to be a dict
        state_dict = _state_to_dict(state)

        return {
            "status": "ok",
            "approved": state_dict.get("consensus", {}).get("approved", False)
            if state_dict.get("consensus")
            else False,
            "executed": state_dict.get("execution", {}).get("executed", False)
            if state_dict.get("execution")
            else False,
            "symbol": state_dict.get("symbol", ""),
            "confidence": state_dict.get("consensus", {}).get("composite_confidence", 0)
            if state_dict.get("consensus")
            else 0,
            "direction": state_dict.get("market_analyst", {}).get("direction", "flat")
            if state_dict.get("market_analyst")
            else "flat",
            "rationale": state_dict.get("execution", {}).get("rationale", "No trade")
            if state_dict.get("execution")
            else "No trade",
            "pipeline_status": state_dict.get("pipeline_status", {}),
            "errors": state_dict.get("errors", []),
        }
    finally:
        lease.release()
        record_analysis_run(status)


def _state_to_dict(state: AgentState) -> dict[str, Any]:
    """Convert an AgentState to a JSON-serializable dict."""
    result: dict[str, Any] = {
        "request_id": state.request_id,
        "session_id": state.session_id,
        "symbol": state.symbol,
        "request": state.request,
        "request_type": state.request_type,
        "pipeline_status": _model_to_dict(state.pipeline_status),
        "errors": state.errors,
        "model_chain_used": state.model_chain_used,
        "degraded": state.degraded,
        "total_latency_ms": state.total_latency_ms,
    }

    for field in (
        "market_analyst",
        "quant",
        "news",
        "vision",
        "consensus",
        "risk",
        "execution",
        "journal",
        "reflection",
        "memory",
    ):
        val = getattr(state, field, None)
        if val is not None:
            result[field] = _model_to_dict(val)
        else:
            result[field] = None

    return result


def _model_to_dict(obj: Any) -> dict[str, Any] | list[Any] | None:
    """Convert a Pydantic model or dataclass to a dict."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()  # type: ignore[no-any-return]
    if hasattr(obj, "_asdict"):
        # noqa: SLF001
        return obj._asdict()  # type: ignore[no-any-return]
    if isinstance(obj, dict):
        return {k: _model_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_model_to_dict(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {f: getattr(obj, f) for f in obj.__dataclass_fields__}
    return obj  # type: ignore[no-any-return]
