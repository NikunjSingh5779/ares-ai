"""Model configuration loader.

Reads the model roster from configs/models.yaml and provides typed access
to model chains, timeouts, and agent metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from configs.settings import PROJECT_ROOT


class AgentModelConfig:
    """Configuration for a single agent's model chain."""

    def __init__(
        self,
        agent_name: str,
        primary: str | None = None,
        fallbacks: list[str] | None = None,
        timeout: int = 30,
        rpm: int = 2,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        breaker_threshold: int = 3,
        breaker_reset_seconds: float = 300,
    ) -> None:
        self.agent_name = agent_name
        self.primary = primary or ""
        self.fallbacks = fallbacks or []
        self.timeout = timeout
        self.rpm = rpm
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.breaker_threshold = breaker_threshold
        self.breaker_reset_seconds = breaker_reset_seconds

    @property
    def model_chain(self) -> list[str]:
        """Full ordered chain: primary + fallbacks (blank-safe for deterministic agents).

        Deterministic agents carry no LLM config, so ``primary`` may be empty
        and the chain is empty — the pipeline must never call an LLM for them.
        """
        chain = [self.primary] if self.primary else []
        chain.extend(f for f in self.fallbacks if f)
        return chain

    @property
    def uses_llm(self) -> bool:
        """True if this agent has at least one configured LLM model."""
        return bool(self.model_chain)

    def has_fallbacks(self) -> bool:
        return len(self.fallbacks) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "primary": self.primary or None,
            "fallbacks": self.fallbacks,
            "timeout": self.timeout,
            "rpm": self.rpm,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "breaker_threshold": self.breaker_threshold,
            "breaker_reset_seconds": self.breaker_reset_seconds,
        }

    @classmethod
    def from_dict(
        cls,
        agent_name: str,
        data: dict[str, Any],
        defaults: dict[str, Any] | None = None,
    ) -> AgentModelConfig:
        """Build config from a raw YAML agent entry, inheriting ``defaults``.

        Repairs loading so that top-level ``defaults`` and every per-agent
        override (``timeout_seconds``, ``rate_limit_rpm``, ``temperature``,
        ``max_tokens``, ``circuit_breaker_threshold``,
        ``circuit_breaker_reset_seconds``) are actually honored. Deterministic
        agents with no ``primary`` key yield an empty, non-LLM chain.
        """
        d = defaults or {}
        return cls(
            agent_name=agent_name,
            primary=data.get("primary"),
            fallbacks=data.get("fallbacks", []),
            timeout=data.get("timeout_seconds", d.get("timeout_seconds", 30)),
            rpm=data.get("rate_limit_rpm", d.get("rate_limit_rpm", 2)),
            temperature=data.get("temperature", d.get("temperature", 0.1)),
            max_tokens=data.get("max_tokens", d.get("max_tokens", 2048)),
            breaker_threshold=data.get("circuit_breaker_threshold", d.get("circuit_breaker_threshold", 3)),
            breaker_reset_seconds=data.get(
                "circuit_breaker_reset_seconds", d.get("circuit_breaker_reset_seconds", 300)
            ),
        )


class ModelRoster:
    """Collection of all agent model configurations."""

    def __init__(self, agents: dict[str, AgentModelConfig]) -> None:
        self._agents = agents

    def get(self, agent_name: str) -> AgentModelConfig:
        """Get config for an agent. Raises KeyError if not found."""
        if agent_name not in self._agents:
            raise KeyError(f"Unknown agent '{agent_name}'. Available: {list(self._agents.keys())}")
        return self._agents[agent_name]

    @property
    def agent_names(self) -> list[str]:
        return list(self._agents.keys())

    def to_dict(self) -> dict[str, Any]:
        return {name: cfg.to_dict() for name, cfg in self._agents.items()}

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ModelRoster:
        agents: dict[str, AgentModelConfig] = {}
        for agent_name, data in config.items():
            agents[agent_name] = AgentModelConfig.from_dict(agent_name, data)
        return cls(agents)


def load_model_roster(path: str | None = None) -> ModelRoster:
    """Load model roster from YAML file.

    Args:
        path: Path to models.yaml. If None, uses CONFIG_DIR / models.yaml.

    Returns:
        ModelRoster with all agent model configs.
    """
    # Use the module-level PROJECT_ROOT constant (not a Settings attribute)
    config_path = Path(path) if path else PROJECT_ROOT / "configs" / "models.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Model roster not found at {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if not raw or "agents" not in raw:
        raise ValueError("Invalid model roster: missing 'agents' key")

    # Repaired loading: top-level ``defaults`` are threaded into every agent
    # entry so default timeout/rpm/temperature/max_tokens/circuit-breaker
    # values are honored unless a per-agent override explicitly replaces them.
    defaults = raw.get("defaults", {})

    agents: dict[str, AgentModelConfig] = {}
    for agent_name, data in raw["agents"].items():
        agents[agent_name] = AgentModelConfig.from_dict(agent_name, data, defaults=defaults)
    return ModelRoster(agents)
