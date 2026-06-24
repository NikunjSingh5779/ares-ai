"""Analysis API router — market analysis and trading signals.

Endpoints:
    POST /api/v1/analyze — Run the full Supervisor pipeline and return state
    POST /api/v1/signal  — Run the pipeline, return the execution result
"""

from __future__ import annotations

from typing import Any
import asyncio

from fastapi import APIRouter, HTTPException, BackgroundTasks

from agents.circuit_breaker import CircuitBreakerRegistry
from agents.client import LLMClient, create_llm_client
from agents.log import AgentLogger
from agents.models import load_model_roster
from agents.queue import QueueRegistry
from agents.registry import AgentRegistry
from agents.retry import RetryConfig
from agents.router import ModelRouter
from agents.state import AgentState
from agents.supervisor import PIPELINE_ORDER, Supervisor
from configs.settings import settings
from database.connection import async_session_factory

router = APIRouter(prefix="/api/v1", tags=["trading"])

# Store the last analysis result in-memory for the dashboard
_last_state: AgentState | None = None

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
    
    from agents.market_analyst import MarketAnalystAgent
    from agents.quant import QuantAgent
    from agents.risk import RiskAgent
    from agents.execution import ExecutionAgent
    from agents.journal import JournalAgent
    from agents.reflection import ReflectionAgent
    from agents.memory import MemoryAgent
    from backend.routers.trading import _get_engine
    from backend.data.ingestor import MarketDataIngestor

    shared_paper_engine = _get_engine()
    shared_ingestor = MarketDataIngestor()

    registry.register("market_analyst", agent=MarketAnalystAgent(router=router_model, ingestor=shared_ingestor))
    registry.register("quant", agent=QuantAgent(router=router_model, ingestor=shared_ingestor))
    registry.register("risk", agent=RiskAgent(router=router_model, ingestor=shared_ingestor))
    registry.register("execution", agent=ExecutionAgent(engine=shared_paper_engine, session_factory=async_session_factory))
    registry.register("journal", agent=JournalAgent(session_factory=async_session_factory))
    registry.register("reflection", agent=ReflectionAgent())
    registry.register("memory", agent=MemoryAgent())

    # Special cased / missing implementation
    registry.register("consensus")
    registry.register("vision")
    
    # "news" is advisory and lacks a real implementation currently.
    # Leaving it unregistered with no agent.
    registry.register("news")

    # 6. Supervisor
    supervisor = Supervisor(
        registry=registry,
        router=router_model,
        logger=logger,
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
        entries.append({
            "id": str(row.id),
            "symbol": row.symbol,
            "direction": row.direction,
            "confidence": float(row.confidence) if row.confidence is not None else 0.0,
            "composite_confidence": float(row.composite_confidence) if row.composite_confidence is not None else 0.0,
            "market_analyst_confidence": float(row.market_analyst_confidence) if row.market_analyst_confidence is not None else 0.0,
            "quant_confidence": float(row.quant_confidence) if row.quant_confidence is not None else 0.0,
            "news_sentiment": float(row.news_sentiment) if row.news_sentiment is not None else 0.0,
            "risk_score": float(row.risk_score) if row.risk_score is not None else 0.0,
            "risk_approved": row.risk_approved,
            "is_consensus": row.is_consensus,
            "rationale": row.rationale,
            "is_executed": row.is_executed,
            "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
            "agent_outputs": row.agent_outputs,
        })

    return entries


def get_last_state() -> AgentState | None:
    """Return the cached last analysis state."""
    return _last_state


async def _background_analysis(supervisor: Supervisor, symbol: str, request_text: str) -> None:
    global _last_state
    try:
        async for state_update in supervisor.stream_analysis(symbol=symbol, request=request_text):
            _last_state = state_update
    except Exception as exc:
        print(f"Background analysis failed: {exc}")


@router.post("/analyze")
async def analyze(body: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Run the full supervisor pipeline for a given symbol and request in the background.

    Returns HTTP 202 Accepted and streams updates to the state.
    """
    global _last_state

    symbol = body.get("symbol", "")
    request_text = body.get("request", "Analyze")

    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    try:
        supervisor = _get_supervisor()
        
        # Initialize a basic state to immediately show in the UI
        from agents.state import AgentState, PipelineStatus
        from datetime import UTC, datetime
        import uuid
        now = datetime.now(UTC).isoformat()
        _last_state = AgentState(
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
                start_time=now
            )
        )

        background_tasks.add_task(_background_analysis, supervisor, symbol, request_text)

        return {"status": "accepted", "message": "Analysis started in background", "session_id": _last_state.session_id}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/signal")
async def signal(body: dict[str, Any]) -> dict[str, Any]:
    """Run the pipeline synchronously and return the consolidated signal result.

    This bypasses background tasks for immediate response.
    """
    symbol = body.get("symbol", "")
    request_text = body.get("request", "Analyze")

    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    supervisor = _get_supervisor()
    state = await supervisor.run_analysis(symbol=symbol, request=request_text)
    
    # Update global state for UI
    global _last_state
    _last_state = state
    
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
        return obj.model_dump()
    if hasattr(obj, "_asdict"):
        return obj._asdict()  # noqa: SLF001
    if isinstance(obj, dict):
        return {k: _model_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_model_to_dict(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {f: getattr(obj, f) for f in obj.__dataclass_fields__}
    return obj
