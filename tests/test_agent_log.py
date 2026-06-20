"""Tests for agent logger."""
from __future__ import annotations

from agents.log import AgentLogger


class TestAgentLogger:
    def test_log_entry_stored(self) -> None:
        logger = AgentLogger()
        entry = logger.log(
            agent_name="test_agent",
            model_id="model-a",
            latency_ms=100,
        )
        assert entry["agent_name"] == "test_agent"
        assert entry["model_id"] == "model-a"
        assert entry["latency_ms"] == 100
        assert entry["error_type"] is None
        assert entry["fallback_used"] is False
        assert entry["degraded"] is False
        assert logger.total_logs == 1

    def test_log_failure(self) -> None:
        logger = AgentLogger()
        logger.log(
            agent_name="test_agent",
            model_id="model-a",
            error_type="ConnectionError",
            latency_ms=500,
            fallback_used=True,
            degraded=True,
        )
        assert logger.total_logs == 1
        failures = logger.get_failures()
        assert len(failures) == 1
        assert failures[0]["error_type"] == "ConnectionError"

    def test_get_recent(self) -> None:
        logger = AgentLogger()
        for i in range(5):
            logger.log(agent_name=f"agent-{i}", latency_ms=i * 10)
        recent = logger.get_recent(3)
        assert len(recent) == 3
        assert recent[0]["agent_name"] == "agent-2"
        assert recent[-1]["agent_name"] == "agent-4"

    def test_get_by_agent(self) -> None:
        logger = AgentLogger()
        logger.log(agent_name="alpha", latency_ms=10)
        logger.log(agent_name="beta", latency_ms=20)
        logger.log(agent_name="alpha", latency_ms=30)

        alpha_logs = logger.get_by_agent("alpha")
        assert len(alpha_logs) == 2
        assert all(e["agent_name"] == "alpha" for e in alpha_logs)

    def test_get_failures_only(self) -> None:
        logger = AgentLogger()
        logger.log(agent_name="a", latency_ms=10)  # success
        logger.log(agent_name="b", latency_ms=20, error_type="TimeoutError")  # failure
        logger.log(agent_name="c", latency_ms=30, error_type="ValueError")  # failure

        failures = logger.get_failures()
        assert len(failures) == 2
        assert all(e["error_type"] is not None for e in failures)

    def test_clear(self) -> None:
        logger = AgentLogger()
        logger.log(agent_name="a", latency_ms=10)
        logger.log(agent_name="b", latency_ms=20)
        assert logger.total_logs == 2
        logger.clear()
        assert logger.total_logs == 0

    def test_to_list(self) -> None:
        logger = AgentLogger()
        logger.log(agent_name="a", latency_ms=10)
        logger.log(agent_name="b", latency_ms=20)
        entries = logger.to_list()
        assert len(entries) == 2

    def test_metadata(self) -> None:
        logger = AgentLogger()
        logger.log(
            agent_name="a",
            model_id="m1",
            metadata={"source": "test", "attempt": 1},
        )
        entries = logger.to_list()
        assert entries[0]["metadata"]["source"] == "test"
        assert entries[0]["metadata"]["attempt"] == 1

    def test_input_output_schema(self) -> None:
        logger = AgentLogger()
        logger.log(
            agent_name="a",
            input_schema={"type": "object", "properties": {"x": {"type": "number"}}},
            output_schema={"type": "object", "properties": {"y": {"type": "string"}}},
        )
        entries = logger.to_list()
        assert entries[0]["input_schema"] is not None
        assert '"type": "object"' in entries[0]["input_schema"]
        assert entries[0]["output_schema"] is not None
