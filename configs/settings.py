"""Settings loader — reads environment + YAML configs.

Provides a single source of truth for all configuration values:
- Env vars via pydantic-settings
- Model roster from configs/models.yaml
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings

# Root project directory (two levels up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All values have defaults — override via .env or environment variables.
    """

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

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    api_secret_key: str = "changeme_in_production"
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
            f"Model roster not found at {roster_path}. "
            f"Run from the project root or ensure configs/models.yaml exists."
        )
    with open(roster_path) as f:
        return yaml.safe_load(f)
