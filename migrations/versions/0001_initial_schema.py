"""Initial schema — baseline for the ARES AI tables.

Revision ID: 0001
Revises:
Create Date: 2025-07-25
"""

import re
from collections.abc import Sequence
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOLLAR_QUOTE = re.compile(r"\$[A-Za-z_0-9]*\$")


def _split_sql(sql: str) -> list[str]:
    """Split PostgreSQL statements without breaking dollar-quoted bodies.

    ``schema.sql`` contains a PL/pgSQL function whose body uses ``$$`` and
    semicolons. Naive ``str.split(";")`` truncates that function, so the
    splitter tracks single quotes, double quotes, and dollar-quote tags.
    """
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    dollar_tag: str | None = None
    index = 0

    while index < len(sql):
        char = sql[index]

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                current.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                current.append(char)
                index += 1
            continue

        if in_single:
            current.append(char)
            if char == "'":
                if index + 1 < len(sql) and sql[index + 1] == "'":
                    current.append("'")
                    index += 2
                    continue
                in_single = False
            index += 1
            continue

        if in_double:
            current.append(char)
            if char == '"':
                if index + 1 < len(sql) and sql[index + 1] == '"':
                    current.append('"')
                    index += 2
                    continue
                in_double = False
            index += 1
            continue

        if char == "'":
            in_single = True
            current.append(char)
            index += 1
            continue
        if char == '"':
            in_double = True
            current.append(char)
            index += 1
            continue
        if char == "$":
            match = _DOLLAR_QUOTE.match(sql, index)
            if match is not None:
                dollar_tag = match.group(0)
                current.append(dollar_tag)
                index += len(dollar_tag)
                continue
        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement + ";")
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail + ";")
    return statements


def upgrade() -> None:
    """Apply the full schema from database/schema.sql."""
    schema_path = Path(__file__).resolve().parent.parent.parent / "database" / "schema.sql"
    schema_sql = schema_path.read_text()
    # Strip full-line comments before splitting. A comment before CREATE TABLE
    # must not cause the whole statement to be skipped.
    schema_sql = "\n".join(line for line in schema_sql.splitlines() if not line.strip().startswith("--"))
    for statement in _split_sql(schema_sql):
        op.execute(statement)


def downgrade() -> None:
    """Drop all tables created by the schema."""
    tables = [
        "improvement_records",
        "reflection_runs",
        "live_trades",
        "paper_trades",
        "backtests",
        "risk_metrics",
        "alerts",
        "metrics",
        "market_data",
        "memories",
        "agent_logs",
        "strategies",
        "journal",
        "trade_history",
        "signals",
        "orders",
        "positions",
        "portfolio",
        "accounts",
        "users",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto;")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp";')
