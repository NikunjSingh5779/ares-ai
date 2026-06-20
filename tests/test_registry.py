"""Tests for agent registry."""
from __future__ import annotations

import pytest

from agents.circuit_breaker import CircuitBreakerRegistry
from agents.models import AgentModelConfig, ModelRoster
from agents.queue import QueueRegistry
from agents.registry import AgentRegistry
from agents.retry import RetryConfig
from agents.router import ModelRouter


@pytest.fixture
def model_roster() -> ModelRoster:
    """Create a minimal model roster for testing."""
    agents = {
        "test_agent": AgentModelConfig.from_dict("test_agent", {"primary": "test-model"}),
        "observer": AgentModelConfig.from_dict("observer", {
            "primary": "obs-model",
            "fallbacks": ["obs-fallback"],
        }),
    }
    return ModelRoster(agents)


@pytest.fixture
def router() -> ModelRouter:
    from agents.client import NoOpLLMClient
    return ModelRouter(
        llm_client=NoOpLLMClient(),
        breaker_registry=CircuitBreakerRegistry(),
        queue_registry=QueueRegistry(),
        retry_config=RetryConfig(max_retries=0, base_delay=0.01),
    )


@pytest.fixture
def registry(model_roster: ModelRoster, router: ModelRouter) -> AgentRegistry:
    return AgentRegistry(
        model_roster=model_roster,
        router=router,
        breaker_registry=CircuitBreakerRegistry(),
        queue_registry=QueueRegistry(),
    )


class TestAgentRegistry:
    def test_register_agent(self, registry: AgentRegistry) -> None:
        registry.register("test_agent")
        reg = registry.get("test_agent")
        assert reg.name == "test_agent"
        assert reg.has_implementation is False

    def test_register_unknown_agent_raises(self, registry: AgentRegistry) -> None:
        with pytest.raises(KeyError, match="Unknown agent"):
            registry.register("nonexistent")

    def test_get_unregistered_raises(self, registry: AgentRegistry) -> None:
        with pytest.raises(KeyError, match="not registered"):
            registry.get("unknown")

    def test_has_agent(self, registry: AgentRegistry) -> None:
        registry.register("test_agent")
        assert registry.has_agent("test_agent") is True
        assert registry.has_agent("unknown") is False

    def test_agent_names(self, registry: AgentRegistry) -> None:
        registry.register("test_agent")
        registry.register("observer")
        names = registry.agent_names
        assert "test_agent" in names
        assert "observer" in names

    def test_get_model_chain(self, registry: AgentRegistry) -> None:
        registry.register("test_agent")
        chain = registry.get_model_chain("test_agent")
        assert chain == ["test-model"]

    def test_get_model_chain_with_fallbacks(self, registry: AgentRegistry) -> None:
        registry.register("observer")
        chain = registry.get_model_chain("observer")
        assert chain == ["obs-model", "obs-fallback"]

    def test_list_agents(self, registry: AgentRegistry) -> None:
        registry.register("test_agent", description="Primary test agent")
        registry.register("observer", description="Observation agent")

        agents = registry.list_agents()
        assert len(agents) == 2

        test_entry = next(a for a in agents if a["name"] == "test_agent")
        assert test_entry["has_implementation"] is False
        assert test_entry["description"] == "Primary test agent"
        assert test_entry["model_chain"] == ["test-model"]

    def test_stats(self, registry: AgentRegistry) -> None:
        registry.register("test_agent")
        registry.register("observer")

        stats = registry.stats()
        assert stats["total_agents"] == 2
        assert stats["with_implementation"] == 0
        assert "breaker_stats" in stats
        assert "queue_stats" in stats
