"""Tests for configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from configs.settings import Settings, settings

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
        "supervisor",
        "coding",
        "market_analyst",
        "quant",
        "risk",
        "news",
        "reflection",
        "memory",
        "vision",
        "fast",
    ]
    for agent_name in required_agents:
        assert agent_name in agents, f"Missing agent: {agent_name}"
        assert agents[agent_name]["primary"], f"{agent_name} agent missing primary model"


def test_vision_agent_fallback_count() -> None:
    """Vision agent fallback count should match expected."""
    data = yaml.safe_load(MODELS_YAML_PATH.read_text())
    vision = data["agents"].get("vision", {})
    fallbacks = vision.get("fallbacks", [])
    # The Vision Agent requires VL (Vision-Language) capabilities.
    # Currently, there are no reliable free-tier VL fallbacks. If the primary
    # VL model is down, it is intentional that it degrades gracefully (skips)
    # without trying an incompatible text-only model.
    assert len(fallbacks) == 0, (
        f"Vision agent should have exactly 0 fallbacks intentionally configured. Got: {fallbacks}"
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


# ── Production-secret rejection tests ────────────────────────────────────


def test_production_rejects_default_api_secret() -> None:
    """If ``api_secret_key`` is still the default, production mode must raise."""
    with pytest.raises(ValueError, match="api_secret_key"):
        Settings(
            environment="production",
            api_secret_key="changeme_in_production",
            jwt_secret_key="real-secret",  # override this one
            database_url="postgresql+asyncpg://ares:real-password@localhost:5432/ares_ai",
        )


def test_production_rejects_default_jwt_secret() -> None:
    """If ``jwt_secret_key`` is still the default, production mode must raise."""
    with pytest.raises(ValueError, match="jwt_secret_key"):
        Settings(
            environment="production",
            api_secret_key="real-secret",
            jwt_secret_key="changeme_in_production",
            database_url="postgresql+asyncpg://ares:real-password@localhost:5432/ares_ai",
        )


def test_production_rejects_default_db_password() -> None:
    """If ``database_url`` still contains the default password, production mode must raise."""
    with pytest.raises(ValueError, match="database_url"):
        Settings(
            environment="production",
            api_secret_key="real-secret",
            jwt_secret_key="real-secret",
            database_url="postgresql+asyncpg://ares:changeme_in_production@localhost:5432/ares_ai",
        )


def test_production_rejects_all_defaults_simultaneously() -> None:
    """All three defaults left in place should mention all three in the error."""
    with pytest.raises(ValueError) as exc_info:
        Settings(
            environment="production",
            api_secret_key="changeme_in_production",
            jwt_secret_key="changeme_in_production",
            database_url="postgresql+asyncpg://ares:changeme_in_production@localhost:5432/ares_ai",
        )
    msg = str(exc_info.value)
    assert "api_secret_key" in msg
    assert "jwt_secret_key" in msg
    assert "database_url" in msg


def test_development_accepts_defaults() -> None:
    """Development mode (the default) MUST NOT reject defaults — local dev
    relies on them before .env is configured."""
    s = Settings(
        api_secret_key="changeme_in_production",
        jwt_secret_key="changeme_in_production",
        database_url="postgresql+asyncpg://ares:changeme_in_production@localhost:5432/ares_ai",
    )
    assert s.environment == "development"


def test_production_allows_custom_secrets() -> None:
    """Production mode with all secrets overridden must succeed."""
    s = Settings(
        environment="production",
        api_secret_key="a1b2c3d4e5-production-secret",
        jwt_secret_key="f6g7h8i9j0-production-secret",
        database_url="postgresql+asyncpg://ares:really-secure-password-42@db.example.com:5432/ares_ai",
    )
    assert s.environment == "production"
    assert s.api_secret_key == "a1b2c3d4e5-production-secret"
