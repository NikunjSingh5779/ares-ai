"""Agent registry — maps agent names to their implementations.

Provides a central registry for all agents in the system.
Each agent is registered with a name, model config, and optional metadata.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from agents.circuit_breaker import CircuitBreakerRegistry
from agents.models import AgentModelConfig, ModelRoster
from agents.queue import QueueRegistry
from agents.router import ModelRouter


class AgentRegistration:
    """Registration entry for a single agent."""

    def __init__(
        self,
        name: str,
        agent: BaseAgent[Any, Any] | None = None,
        model_config: AgentModelConfig | None = None,
        description: str = "",
    ) -> None:
        self.name = name
        self.agent = agent
        self.model_config = model_config
        self.description = description

    @property
    def has_implementation(self) -> bool:
        return self.agent is not None


class AgentRegistry:
    """Central registry for all agents in the system.

    Agents can be registered with or without implementations.
    In M3, agents are registered as stubs; implementations come in M4+.
    """

    def __init__(
        self,
        model_roster: ModelRoster,
        router: ModelRouter,
        breaker_registry: CircuitBreakerRegistry,
        queue_registry: QueueRegistry,
    ) -> None:
        self._model_roster = model_roster
        self._router = router
        self._breakers = breaker_registry
        self._queues = queue_registry
        self._agents: dict[str, AgentRegistration] = {}

    def register(
        self,
        name: str,
        agent: BaseAgent[Any, Any] | None = None,
        description: str = "",
    ) -> None:
        """Register an agent.

        Args:
            name: Agent name (must have a model config).
            agent: Optional BaseAgent implementation.
            description: Human-readable description.

        Raises:
            KeyError: If no model config exists for this agent name.
        """
        model_config = self._model_roster.get(name)
        self._agents[name] = AgentRegistration(
            name=name,
            agent=agent,
            model_config=model_config,
            description=description or f"{name} agent",
        )

    def get(self, name: str) -> AgentRegistration:
        """Get an agent registration. Raises KeyError if not found."""
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not registered. Available: {list(self._agents.keys())}")
        return self._agents[name]

    @property
    def agent_names(self) -> list[str]:
        return list(self._agents.keys())

    def get_model_chain(self, agent_name: str) -> list[str]:
        """Get the full model chain for an agent."""
        reg = self.get(agent_name)
        return reg.model_config.model_chain  # type: ignore[union-attr]

    def has_agent(self, name: str) -> bool:
        return name in self._agents

    def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents with metadata."""
        result = []
        for name, reg in self._agents.items():
            result.append({
                "name": name,
                "has_implementation": reg.has_implementation,
                "description": reg.description,
                "model_chain": reg.model_config.model_chain if reg.model_config else [],  # type: ignore[union-attr]
            })
        return result

    def stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_agents": len(self._agents),
            "with_implementation": sum(1 for r in self._agents.values() if r.has_implementation),
            "agents": self.list_agents(),
            "breaker_stats": self._breakers.all_stats(),
            "queue_stats": self._queues.all_stats(),
        }
