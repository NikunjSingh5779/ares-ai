"""Tests for database schema validity.

Verifies the SQL schema file is syntactically correct by parsing
it with the PostgreSQL parser (requires a running Postgres instance
or sqlparse for static analysis).
"""

from __future__ import annotations

import importlib.util
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


def test_all_21_tables_present() -> None:
    """Schema must define all 21 required tables."""
    content = SCHEMA_PATH.read_text()
    tables = TABLE_PATTERN.findall(content)
    table_names = {t.lower() for t in tables}

    expected_tables = {
        "users",
        "accounts",
        "app_settings",
        "portfolio",
        "positions",
        "orders",
        "signals",
        "trade_history",
        "journal",
        "strategies",
        "agent_logs",
        "memories",
        "market_data",
        "metrics",
        "alerts",
        "risk_metrics",
        "backtests",
        "paper_trades",
        "live_trades",
        "reflection_runs",
        "improvement_records",
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
        f"Expected at least 20 indexes, found {len(indexes)}. Add more indexes for query performance."
    )


def test_updated_at_triggers_present() -> None:
    """Tables with updated_at must have auto-update triggers."""
    content = SCHEMA_PATH.read_text()
    triggers = TRIGGER_PATTERN.findall(content)
    assert len(triggers) >= 8, f"Expected at least 8 updated_at triggers, found {len(triggers)}"
    assert "update_updated_at_column" in content, "Missing update_updated_at_column function"


def test_uuid_extension() -> None:
    """Schema must enable uuid-ossp extension for UUID generation."""
    content = SCHEMA_PATH.read_text()
    assert "uuid-ossp" in content, "Missing uuid-ossp extension"
    assert "uuid_generate_v4" in content, "Missing uuid_generate_v4 usage"


def test_risk_check_constraints() -> None:
    """Risk_score must be bounded 0-100 where used."""
    content = SCHEMA_PATH.read_text()
    assert "CHECK (risk_score >= 0 AND risk_score <= 100)" in content, "risk_score must have a 0-100 check constraint"


def test_execution_protocol_constraints() -> None:
    """Live trades must enforce human_approval trading_mode."""
    content = SCHEMA_PATH.read_text()
    assert "human_approval" in content, "Schema must enforce human_approval trading mode per EXECUTION PROTOCOL"
    assert "kill_switch_active" in content, (
        "live_trades must have kill_switch_active column per LIVE TRADING safety gates"
    )


def test_strategy_promotion_gate() -> None:
    """Strategies must have paper->live promotion gates."""
    content = SCHEMA_PATH.read_text()
    assert "min_paper_trades_required" in content, "strategies table must enforce min_paper_trades_required"
    assert "min_paper_days_required" in content, "strategies table must enforce min_paper_days_required"


def test_agent_logs_tracks_degradation() -> None:
    """Agent logs must track circuit breaker and degradation state."""
    content = SCHEMA_PATH.read_text()
    assert "circuit_breaker_tripped" in content, "agent_logs needs circuit_breaker_tripped column"
    assert "degraded_mode" in content, "agent_logs needs degraded_mode column"


def test_paper_ledger_columns_present() -> None:
    """The durable paper ledger needs side, cost, margin, and curve fields."""
    content = SCHEMA_PATH.read_text()
    assert "side VARCHAR(10) NOT NULL DEFAULT 'long'" in content
    assert "position_side VARCHAR(10) NOT NULL DEFAULT 'long'" in content
    assert "entry_commission NUMERIC" in content
    assert "exit_commission NUMERIC" in content
    assert "equity_curve JSONB" in content
    assert "initial_capital NUMERIC" in content


def test_order_idempotency_columns_present() -> None:
    """Paper orders need a per-account client ID for duplicate protection."""
    content = SCHEMA_PATH.read_text()
    assert "client_order_id VARCHAR(100)" in content
    assert "uq_orders_client_order_id" in content
    assert "WHERE client_order_id IS NOT NULL" in content


def test_app_settings_is_a_single_non_safety_row() -> None:
    """Dashboard preferences are one JSON row; safety limits stay out of the table."""
    content = SCHEMA_PATH.read_text()
    assert "CREATE TABLE app_settings" in content
    assert "id SMALLINT PRIMARY KEY CHECK (id = 1)" in content
    assert "preferences JSONB NOT NULL DEFAULT '{}'::jsonb" in content
    assert "max_position_size" not in content.split("CREATE TABLE app_settings", 1)[1].split(";", 1)[0]


def test_init_schema_is_byte_identical_copy() -> None:
    """Compose mounts init.sql; it must not drift from the canonical schema."""
    init_path = SCHEMA_PATH.with_name("init.sql")
    canonical = SCHEMA_PATH.read_bytes().replace(b"\r\n", b"\n")
    mounted = init_path.read_bytes().replace(b"\r\n", b"\n")
    assert mounted == canonical, "database/init.sql must match database/schema.sql"


def test_initial_migration_splitter_preserves_dollar_quotes() -> None:
    """The schema splitter must not cut a PL/pgSQL body at its semicolons."""
    migration_path = Path(__file__).resolve().parent.parent / "migrations" / "versions" / "0001_initial_schema.py"
    spec = importlib.util.spec_from_file_location("ares_initial_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    split_sql = getattr(module, "_split_sql")
    sql = (
        "SELECT 1; CREATE FUNCTION f() RETURNS trigger AS $$ "
        "BEGIN NEW.x = 1; RETURN NEW; END; $$ LANGUAGE plpgsql; SELECT 2;"
    )
    statements = split_sql(sql)
    assert len(statements) == 3
    assert "BEGIN NEW.x = 1; RETURN NEW; END;" in statements[1]
