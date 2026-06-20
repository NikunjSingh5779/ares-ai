"""Tests for configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from configs.settings import load_model_roster, settings

MODELS_YAML_PATH = Path(__file__).resolve().parent.parent / "configs" / "models.yaml"


def test_settings_loaded() -> None:
    """Settings singleton loads without error."""
    assert settings is not None
    assert hasattr(settings, "database_url")
    assert hasattr(settings, "api_port")


def test_settings_defaults() -> None:
    """Default values are reasonable."""
    assert settings.api_port == 8000
    assert settings.api_rate_limit_per_minute == 100
    assert settings.paper_trading_initial_capital == 100000.0
    assert settings.default_trading_mode == "human_approval"
    assert settings.max_drawdown_pct == 20.0


def test_models_yaml_exists() -> None:
    """Model roster file must exist."""
    assert MODELS_YAML_PATH.exists(), f"models.yaml not found at {MODELS_YAML_PATH}"


def test_models_yaml_valid() -> None:
    """Model roster must be valid YAML."""
    content = MODELS_YAML_PATH.read_text()
    data = yaml.safe_load(content)
    assert data is not None, "models.yaml is empty or invalid"
    assert "defaults" in data, "models.yaml must have a 'defaults' section"
    assert "agents" in data, "models.yaml must have an 'agents' section"


def test_all_agents_have_models() -> None:
    """Every agent in models.yaml must have a primary model."""
    data = yaml.safe_load(MODELS_YAML_PATH.read_text())
    agents = data["agents"]
    required_agents = [
        "supervisor", "coding", "market_analyst", "quant", "risk",
        "news", "reflection", "memory", "vision", "fast",
    ]
    for agent_name in required_agents:
        assert agent_name in agents, f"Missing agent: {agent_name}"
        assert agents[agent_name]["primary"], (
            f"{agent_name} agent missing primary model"
        )


def test_vision_agent_fallback_count() -> None:
    """Vision agent fallback count should match expected."""
    data = yaml.safe_load(MODELS_YAML_PATH.read_text())
    vision = data["agents"].get("vision", {})
    fallbacks = vision.get("fallbacks", [])
    # At least one VL fallback should be configured; if the primary is down,
    # the system degrades gracefully (skips, not blocks).
    assert len(fallbacks) >= 1, (
        "Vision agent should have at least one VL fallback configured. "
        f"Got: {fallbacks}"
    )


def test_circuit_breaker_defaults() -> None:
    """Defaults section must have circuit breaker config."""
    data = yaml.safe_load(MODELS_YAML_PATH.read_text())
    defaults = data["defaults"]
    assert "circuit_breaker_threshold" in defaults
    assert "circuit_breaker_reset_seconds" in defaults
    assert defaults["circuit_breaker_threshold"] >= 1


def test_models_yaml_timeouts() -> None:
    """Every agent with a custom timeout must have a reasonable value."""
    data = yaml.safe_load(MODELS_YAML_PATH.read_text())
    for name, cfg in data["agents"].items():
        timeout = cfg.get("timeout_seconds", data["defaults"]["timeout_seconds"])
        assert timeout > 0, f"{name} agent has invalid timeout: {timeout}"
        assert timeout <= 300, f"{name} agent timeout too high: {timeout} (max 300)"
