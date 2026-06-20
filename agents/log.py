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


class AgentLogger:
    """Logs agent execution data to the agent_logs table.

    Can operate with or without a database session.
    Without a session, logs are queued in memory.
    """

    def __init__(self) -> None:
        self._logs: list[dict[str, Any]] = []

    def log(
        self,
        agent_name: str,
        state_snapshot: dict[str, Any] | None = None,
        model_id: str | None = None,
        error_type: str | None = None,
        latency_ms: int = 0,
        fallback_used: bool = False,
        degraded: bool = False,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an agent execution log entry.

        Args:
            agent_name: Name of the agent that executed.
            state_snapshot: Optional state snapshot at execution time.
            model_id: The model ID that was used (or attempted).
            error_type: Error type string if the call failed.
            latency_ms: Total execution latency in milliseconds.
            fallback_used: Whether a fallback model was used.
            degraded: Whether the call ran in degraded mode.
            input_schema: The input schema used for this agent.
            output_schema: The output schema used for this agent.
            metadata: Additional metadata.

        Returns:
            The log entry dict.
        """
        entry: dict[str, Any] = {
            "agent_name": agent_name,
            "timestamp": datetime.now(UTC).isoformat(),
            "model_id": model_id or "",
            "error_type": error_type,
            "latency_ms": latency_ms,
            "fallback_used": fallback_used,
            "degraded": degraded,
            "input_schema": json.dumps(input_schema) if input_schema else None,
            "output_schema": json.dumps(output_schema) if output_schema else None,
            "state_snapshot": state_snapshot,
            "metadata": metadata or {},
        }
        self._logs.append(entry)
        return entry

    def get_recent(self, n: int = 10) -> list[dict[str, Any]]:
        """Get the most recent N log entries."""
        return self._logs[-n:]

    def get_by_agent(self, agent_name: str) -> list[dict[str, Any]]:
        """Get all log entries for a specific agent."""
        return [e for e in self._logs if e["agent_name"] == agent_name]

    def get_failures(self) -> list[dict[str, Any]]:
        """Get all log entries with errors."""
        return [e for e in self._logs if e["error_type"] is not None]

    @property
    def total_logs(self) -> int:
        return len(self._logs)

    def clear(self) -> None:
        """Clear all in-memory logs."""
        self._logs.clear()

    def to_list(self) -> list[dict[str, Any]]:
        """Get all log entries as a list."""
        return list(self._logs)

    async def flush_to_db(self, session: Any) -> int:
        """Flush all buffered logs to the agent_logs table.

        Args:
            session: An async SQLAlchemy session.

        Returns:
            Number of rows flushed.
        """
        if not self._logs:
            return 0

        values = []
        for entry in self._logs:
            values.append({
                "agent_name": entry["agent_name"],
                "model_id": entry["model_id"],
                "error_type": entry["error_type"],
                "latency_ms": entry["latency_ms"],
                "fallback_used": entry["fallback_used"],
                "degraded": entry["degraded"],
                "input_schema": entry["input_schema"],
                "output_schema": entry["output_schema"],
                "metadata": json.dumps(entry.get("metadata", {})),
            })

        stmt = text("""
            INSERT INTO agent_logs
                (agent_name, model_id, error_type, latency_ms,
                 fallback_used, degraded, input_schema, output_schema, metadata)
            VALUES
                (:agent_name, :model_id, :error_type, :latency_ms,
                 :fallback_used, :degraded, :input_schema, :output_schema, :metadata::jsonb)
        """)

        count = len(values)
        for v in values:
            await session.execute(stmt, v)
        await session.commit()
        self._logs.clear()
        return count
