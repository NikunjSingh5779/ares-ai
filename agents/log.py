"""Agent logging service.

Logs all agent calls to the agent_logs table for audit and debugging.
Implements the RELIABILITY section requirement:
- All failures logged with model id, error type, latency, fallback used
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text


from database.connection import async_session_factory

class AgentLogger:
    """Logs agent execution data directly to the agent_logs table."""

    def __init__(self) -> None:
        pass

    async def log(
        self,
        agent_name: str,
        model_used: str = "",
        model_chain: list[str] | None = None,
        success: bool = True,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        latency_ms: int = 0,
        token_count: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
        retry_count: int = 0,
        circuit_breaker_tripped: bool = False,
        degraded_mode: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Record an agent execution log entry directly to the database."""
        model_chain = model_chain or []
        stmt = text("""
            INSERT INTO agent_logs
                (agent_name, model_used, model_chain, input_schema, output_schema,
                 input_data, output_data, latency_ms, token_count, success,
                 error_type, error_message, retry_count, circuit_breaker_tripped, degraded_mode)
            VALUES
                (:agent_name, :model_used, :model_chain, CAST(:input_schema AS jsonb), CAST(:output_schema AS jsonb),
                 CAST(:input_data AS jsonb), CAST(:output_data AS jsonb), :latency_ms, :token_count, :success,
                 :error_type, :error_message, :retry_count, :circuit_breaker_tripped, :degraded_mode)
        """)
        
        async with async_session_factory() as session:
            await session.execute(stmt, {
                "agent_name": agent_name,
                "model_used": model_used,
                "model_chain": model_chain,
                "input_schema": json.dumps(input_schema) if input_schema else None,
                "output_schema": json.dumps(output_schema) if output_schema else None,
                "input_data": json.dumps(input_data) if input_data else None,
                "output_data": json.dumps(output_data) if output_data else None,
                "latency_ms": latency_ms,
                "token_count": token_count,
                "success": success,
                "error_type": error_type,
                "error_message": error_message,
                "retry_count": retry_count,
                "circuit_breaker_tripped": circuit_breaker_tripped,
                "degraded_mode": degraded_mode,
            })
            await session.commit()
            
        return {}
