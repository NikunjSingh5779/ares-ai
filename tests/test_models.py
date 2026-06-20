"""Tests for model configuration loader."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agents.models import AgentModelConfig, ModelRoster, load_model_roster

# Sample model roster for testing
SAMPLE_ROSTER = {
    "agents": {
        "supervisor": {
            "primary": "opencode/deepseek-v4-flash-free",
            "fallbacks": ["open_router/qwen/qwen3-next-80b-a3b-instruct:free"],
            "timeout": 60,
            "rpm": 20,
        },
        "market_analyst": {
            "primary": "open_router/nvidia/nemotron-3-ultra-550b-a55b:free",
            "fallbacks": [
                "open_router/qwen/qwen3-next-80b-a3b-instruct:free",
                "open_router/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            ],
            "timeout": 120,
            "rpm": 10,
        },
        "vision": {
            "primary": "open_router/nvidia/nemotron-nano-12b-v2-vl:free",
            "fallbacks": [],
            "timeout": 60,
            "rpm": 5,
        },
    },
}


@pytest.fixture
def sample_config() -> dict:
    return SAMPLE_ROSTER["agents"]


class TestAgentModelConfig:
    def test_from_dict_basic(self) -> None:
        cfg = AgentModelConfig.from_dict("supervisor", SAMPLE_ROSTER["agents"]["supervisor"])
        assert cfg.agent_name == "supervisor"
        assert cfg.primary == "opencode/deepseek-v4-flash-free"
        assert cfg.fallbacks == ["open_router/qwen/qwen3-next-80b-a3b-instruct:free"]
        assert cfg.timeout == 60
        assert cfg.rpm == 20

    def test_model_chain(self) -> None:
        cfg = AgentModelConfig.from_dict("market_analyst", SAMPLE_ROSTER["agents"]["market_analyst"])
        chain = cfg.model_chain
        assert len(chain) == 3
        assert chain[0] == cfg.primary
        assert chain[1] == cfg.fallbacks[0]
        assert chain[2] == cfg.fallbacks[1]

    def test_no_fallbacks(self) -> None:
        cfg = AgentModelConfig.from_dict("vision", SAMPLE_ROSTER["agents"]["vision"])
        assert cfg.fallbacks == []
        assert cfg.has_fallbacks() is False
        assert len(cfg.model_chain) == 1

    def test_has_fallbacks(self) -> None:
        cfg = AgentModelConfig.from_dict("supervisor", SAMPLE_ROSTER["agents"]["supervisor"])
        assert cfg.has_fallbacks() is True

    def test_default_values(self) -> None:
        cfg = AgentModelConfig.from_dict("test", {"primary": "test-model"})
        assert cfg.fallbacks == []
        assert cfg.timeout == 60
        assert cfg.rpm == 20
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096

    def test_to_dict(self) -> None:
        cfg = AgentModelConfig.from_dict("supervisor", SAMPLE_ROSTER["agents"]["supervisor"])
        d = cfg.to_dict()
        assert d["agent_name"] == "supervisor"
        assert d["primary"] == "opencode/deepseek-v4-flash-free"
        assert len(d["fallbacks"]) == 1


class TestModelRoster:
    @pytest.fixture
    def roster(self) -> ModelRoster:
        agents = {}
        for name, data in SAMPLE_ROSTER["agents"].items():
            agents[name] = AgentModelConfig.from_dict(name, data)
        return ModelRoster(agents)

    def test_get_existing(self, roster: ModelRoster) -> None:
        cfg = roster.get("supervisor")
        assert cfg.agent_name == "supervisor"
        assert cfg.primary == "opencode/deepseek-v4-flash-free"

    def test_get_unknown_raises(self, roster: ModelRoster) -> None:
        with pytest.raises(KeyError, match="Unknown agent"):
            roster.get("nonexistent")

    def test_agent_names(self, roster: ModelRoster) -> None:
        names = roster.agent_names
        assert "supervisor" in names
        assert "market_analyst" in names
        assert "vision" in names
        assert len(names) == 3

    def test_from_config_classmethod(self) -> None:
        roster = ModelRoster.from_config(SAMPLE_ROSTER["agents"])
        assert roster.get("supervisor") is not None
        assert roster.get("market_analyst") is not None

    def test_to_dict(self, roster: ModelRoster) -> None:
        d = roster.to_dict()
        assert "supervisor" in d
        assert d["supervisor"]["primary"] == "opencode/deepseek-v4-flash-free"


class TestLoadModelRoster:
    def test_load_from_path(self, tmp_path: Path) -> None:
        config_file = tmp_path / "models.yaml"
        with open(config_file, "w") as f:
            yaml.dump(SAMPLE_ROSTER, f)

        roster = load_model_roster(str(config_file))
        assert roster.get("supervisor") is not None
        assert roster.get("market_analyst") is not None
        assert roster.get("vision") is not None

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            load_model_roster("/nonexistent/path/models.yaml")

    def test_missing_agents_key(self, tmp_path: Path) -> None:
        config_file = tmp_path / "models.yaml"
        with open(config_file, "w") as f:
            yaml.dump({"not_agents": {}}, f)

        with pytest.raises(ValueError, match="missing 'agents' key"):
            load_model_roster(str(config_file))
