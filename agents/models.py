"""Model configuration loader.

Reads the model roster from configs/models.yaml and provides typed access
to model chains, timeouts, and agent metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from configs.settings import get_settings


class AgentModelConfig:
    """Configuration for a single agent's model chain."""

    def __init__(
        self,
        agent_name: str,
        primary: str,
        fallbacks: list[str] | None = None,
        timeout: int = 60,
        rpm: int = 20,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        self.agent_name = agent_name
        self.primary = primary
        self.fallbacks = fallbacks or []
        self.timeout = timeout
        self.rpm = rpm
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def model_chain(self) -> list[str]:
        """Full ordered chain: primary + fallbacks."""
        return [self.primary, *self.fallbacks]

    def has_fallbacks(self) -> bool:
        return len(self.fallbacks) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "primary": self.primary,
            "fallbacks": self.fallbacks,
            "timeout": self.timeout,
            "rpm": self.rpm,
        }

    @classmethod
    def from_dict(cls, agent_name: str, data: dict[str, Any]) -> AgentModelConfig:
        return cls(
            agent_name=agent_name,
            primary=data["primary"],
            fallbacks=data.get("fallbacks", []),
            timeout=data.get("timeout", 60),
            rpm=data.get("rpm", 20),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 4096),
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
    settings = get_settings()
    # Use PROJECT_ROOT / configs / models.yaml
    config_path = Path(path) if path else settings.PROJECT_ROOT / "configs" / "models.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Model roster not found at {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if not raw or "agents" not in raw:
        raise ValueError("Invalid model roster: missing 'agents' key")

    return ModelRoster.from_config(raw["agents"])
