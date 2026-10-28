"""Tests for configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agents.risk import MAX_POSITION_SIZE_PCT
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


def test_position_cap_is_code_enforced_not_environment_configurable() -> None:
    """The 2% exposure cap must not be weakened by an environment override."""
    assert "max_position_size_pct" not in Settings.model_fields
    assert MAX_POSITION_SIZE_PCT == 2.0


def test_paper_accounting_defaults_are_realistic() -> None:
    """The application should not run paper trades with frictionless fills."""
    fields = Settings.model_fields
    assert fields["paper_trading_commission_pct"].default == 0.001
    assert fields["paper_trading_slippage_pct"].default == 0.001


def test_paper_writer_lock_timeout_is_positive() -> None:
    """A non-positive lock timeout would make every paper write fail busy."""
    assert Settings.model_fields["paper_trading_writer_lock_timeout_seconds"].default == 10.0
    with pytest.raises(ValidationError):
        Settings(paper_trading_writer_lock_timeout_seconds=0)


def test_approval_token_lifetime_is_short_and_bounded() -> None:
    """A leaked /execute approval token must expire quickly and stay bounded."""
    assert Settings.model_fields["approval_token_expire_minutes"].default == 5
    with pytest.raises(ValidationError):
        Settings(approval_token_expire_minutes=0)
    with pytest.raises(ValidationError):
        Settings(approval_token_expire_minutes=31)


def test_production_compose_overlays_enable_production() -> None:
    """Production overlays must actually flip ENVIRONMENT=production."""
    root = Path(__file__).resolve().parent.parent
    overlays = {
        root / "docker-compose.prod.yml": {"backend", "run-live", "daily-reporter"},
        root / "docker" / "docker-compose.prod.yml": {"backend"},
    }
    for path, required_services in overlays.items():
        data = yaml.safe_load(path.read_text())
        services = data["services"]
        for service in required_services:
            assert services[service]["environment"]["ENVIRONMENT"] == "production", (
                f"{path.name} must set ENVIRONMENT=production for {service}"
            )


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


def test_vision_agent_fallbacks_are_configured_and_free() -> None:
    """Vision fallbacks must exist and stay on the free tier.

    The roster now has validated image-capable free models; a text-only
    fallback would fail at runtime, so every entry must be a free ID.
    """
    data = yaml.safe_load(MODELS_YAML_PATH.read_text())
    vision = data["agents"].get("vision", {})
    fallbacks = vision.get("fallbacks", [])
    assert len(fallbacks) >= 1, "Vision agent should have at least one fallback"
    assert all(fallback.endswith(":free") or fallback.endswith("/free") for fallback in fallbacks)


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


def test_local_llm_defaults_are_opt_in_and_single_request(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "LOCAL_LLM_ENABLED",
        "LOCAL_LLM_BASE_URL",
        "LOCAL_LLM_TIMEOUT_SECONDS",
        "LOCAL_LLM_MAX_CONCURRENT",
        "LOCAL_LLM_QUEUE_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)

    s = Settings()

    assert s.local_llm_enabled is False
    assert s.local_llm_base_url == "http://127.0.0.1:8080/v1"
    assert s.local_llm_timeout_seconds == 90.0
    assert s.local_llm_max_concurrent == 1
    assert s.local_llm_queue_timeout_seconds == 20.0


def test_local_llm_rejects_invalid_gate_limits() -> None:
    with pytest.raises(ValidationError):
        Settings(local_llm_max_concurrent=0)
    with pytest.raises(ValidationError):
        Settings(local_llm_queue_timeout_seconds=0)
