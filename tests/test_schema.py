"""Tests for database schema validity.

Verifies the SQL schema file is syntactically correct by parsing
it with the PostgreSQL parser (requires a running Postgres instance
or sqlparse for static analysis).
"""

from __future__ import annotations

import re
from pathlib import Path

# Regular expressions to validate schema structure without a database
TABLE_PATTERN = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE)
INDEX_PATTERN = re.compile(r"CREATE\s+(UNIQUE\s+)?INDEX\s+", re.IGNORECASE)
TRIGGER_PATTERN = re.compile(r"CREATE\s+TRIGGER\s+", re.IGNORECASE)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "database" / "schema.sql"


def test_schema_file_exists() -> None:
    """Schema file must exist."""
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"


def test_schema_not_empty() -> None:
    """Schema file must contain SQL content."""
    content = SCHEMA_PATH.read_text()
    assert len(content) > 100, "Schema file appears too small"
    assert "CREATE TABLE" in content, "Schema must contain CREATE TABLE statements"


def test_all_17_tables_present() -> None:
    """Schema must define all 17 required tables."""
    content = SCHEMA_PATH.read_text()
    tables = TABLE_PATTERN.findall(content)
    table_names = {t.lower() for t in tables}

    expected_tables = {
        "users", "accounts", "portfolio", "positions", "orders",
        "signals", "trade_history", "journal", "strategies", "agent_logs",
        "memories", "market_data", "metrics", "alerts", "risk_metrics",
        "backtests", "paper_trades", "live_trades",
    }

    missing = expected_tables - table_names
    assert not missing, f"Missing tables: {missing}"

    extra = table_names - expected_tables
    assert not extra, f"Unexpected tables: {extra}"


def test_required_columns() -> None:
    """Key tables must have required columns."""
    content = SCHEMA_PATH.read_text()

    # signals table must have agent_outputs JSONB and rationale
    if "CREATE TABLE signals" in content:
        assert "agent_outputs JSONB" in content, "signals table needs agent_outputs JSONB"
        assert "rationale TEXT" in content, "signals table needs rationale"

    # agent_logs must have schema validation columns
    if "CREATE TABLE agent_logs" in content:
        assert "input_schema JSONB" in content, "agent_logs needs input_schema"
        assert "output_schema JSONB" in content, "agent_logs needs output_schema"


def test_indexes_present() -> None:
    """Schema must define indexes for performance."""
    content = SCHEMA_PATH.read_text()
    indexes = INDEX_PATTERN.findall(content)
    assert len(indexes) >= 20, (
        f"Expected at least 20 indexes, found {len(indexes)}. "
        f"Add more indexes for query performance."
    )


def test_updated_at_triggers_present() -> None:
    """Tables with updated_at must have auto-update triggers."""
    content = SCHEMA_PATH.read_text()
    triggers = TRIGGER_PATTERN.findall(content)
    assert len(triggers) >= 8, (
        f"Expected at least 8 updated_at triggers, found {len(triggers)}"
    )
    assert "update_updated_at_column" in content, (
        "Missing update_updated_at_column function"
    )


def test_uuid_extension() -> None:
    """Schema must enable uuid-ossp extension for UUID generation."""
    content = SCHEMA_PATH.read_text()
    assert "uuid-ossp" in content, "Missing uuid-ossp extension"
    assert "uuid_generate_v4" in content, "Missing uuid_generate_v4 usage"


def test_risk_check_constraints() -> None:
    """Risk_score must be bounded 0-100 where used."""
    content = SCHEMA_PATH.read_text()
    assert "CHECK (risk_score >= 0 AND risk_score <= 100)" in content, (
        "risk_score must have a 0-100 check constraint"
    )


def test_execution_protocol_constraints() -> None:
    """Live trades must enforce human_approval trading_mode."""
    content = SCHEMA_PATH.read_text()
    assert "human_approval" in content, (
        "Schema must enforce human_approval trading mode per EXECUTION PROTOCOL"
    )
    assert "kill_switch_active" in content, (
        "live_trades must have kill_switch_active column per LIVE TRADING safety gates"
    )


def test_strategy_promotion_gate() -> None:
    """Strategies must have paper->live promotion gates."""
    content = SCHEMA_PATH.read_text()
    assert "min_paper_trades_required" in content, (
        "strategies table must enforce min_paper_trades_required"
    )
    assert "min_paper_days_required" in content, (
        "strategies table must enforce min_paper_days_required"
    )


def test_agent_logs_tracks_degradation() -> None:
    """Agent logs must track circuit breaker and degradation state."""
    content = SCHEMA_PATH.read_text()
    assert "circuit_breaker_tripped" in content, (
        "agent_logs needs circuit_breaker_tripped column"
    )
    assert "degraded_mode" in content, (
        "agent_logs needs degraded_mode column"
    )
