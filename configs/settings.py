"""Settings loader — reads environment + YAML configs.

Provides a single source of truth for all configuration values:
- Env vars via pydantic-settings
- Model roster from configs/models.yaml
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings

# Root project directory (two levels up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All values have defaults — override via .env or environment variables.

    **Production safety**: if ``environment == "production"`` and any of
    ``api_secret_key``, ``jwt_secret_key``, or the password inside
    ``database_url`` still equals ``"changeme_in_production"``, the
    application refuses to start.  This is enforced by a Pydantic
    ``model_validator`` that runs when ``Settings()`` is constructed.
    """

    # Runtime environment — used for production-safety gates
    environment: Literal["development", "test", "production"] = "development"

    # Database
    database_url: str = "postgresql+asyncpg://ares:changeme_in_production@localhost:5432/ares_ai"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_collection: str = "ares_memories"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # OpenCode (fallback)
    opencode_api_key: str = ""
    opencode_base_url: str = "https://api.opencode.ai/v1"

    # Google AI Studio (Gemini)
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # Mistral AI
    mistral_api_key: str = ""
    mistral_base_url: str = "https://api.mistral.ai/v1"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    api_secret_key: str = "changeme_in_production"
    jwt_secret_key: str = "changeme_in_production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    api_rate_limit_per_minute: int = 100
    api_cors_origins: str = "http://localhost:3000"

    # Trading defaults
    paper_trading_initial_capital: float = 100000.0
    kill_switch_enabled: bool = True
    default_trading_mode: str = "human_approval"
    max_position_size_pct: float = 5.0
    max_drawdown_pct: float = 20.0

    # Live trading exchange
    exchange_name: str = "binance"
    exchange_api_key: str = ""
    exchange_secret_key: str = ""
    exchange_testnet: bool = True

    # Coinbase
    coinbase_api_key: str = ""
    coinbase_secret_key: str = ""

    # Kraken
    kraken_api_key: str = ""
    kraken_secret_key: str = ""

    minimum_paper_trades: int = 50
    minimum_paper_days: int = 30
    live_max_drawdown_pct: float = 15.0

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Monitoring
    prometheus_port: int = 9090
    grafana_port: int = 3001
    health_check_interval_seconds: int = 30

    # ── Production-safety validator ──────────────────────────────────

    @model_validator(mode="after")
    def _reject_default_secrets_in_production(self) -> "Settings":
        """Refuse to start if production mode is set but defaults remain.

        Checks ``api_secret_key``, ``jwt_secret_key``, and the embedded
        password inside ``database_url`` — all three must be overridden
        when ``environment == "production"``.
        """
        if self.environment != "production":
            return self

        failures: list[str] = []

        if self.api_secret_key == "changeme_in_production":
            failures.append("api_secret_key")
        if self.jwt_secret_key == "changeme_in_production":
            failures.append("jwt_secret_key")
        if "changeme_in_production" in self.database_url:
            failures.append("database_url (password still contains 'changeme_in_production')")

        if failures:
            msg = (
                "SECURITY: Production environment was requested but the"
                f" following secret(s) still use the default value"
                f" 'changeme_in_production': {', '.join(failures)}.\n"
                "  Set the corresponding environment variable or .env entry"
                " to a unique, non-default value before running in production."
            )
            raise ValueError(msg)

        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


# Global singleton
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings singleton."""
    return settings


def load_model_roster() -> dict[str, Any]:
    """Load the model roster from configs/models.yaml."""
    roster_path = PROJECT_ROOT / "configs" / "models.yaml"
    if not roster_path.exists():
        raise FileNotFoundError(
            f"Model roster not found at {roster_path}. Run from the project root or ensure configs/models.yaml exists."
        )
    with open(roster_path) as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]
