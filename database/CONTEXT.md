<!-- database/CONTEXT.md -->
# database/ — contract

**Purpose:** PostgreSQL schema, async connection factory, and ORM models.

## Files
- `schema.sql` — canonical DDL for all 18 tables (users … live_trades).
- `init.sql` — byte-identical copy mounted by compose. **Duplicate, not canonical.**
- `connection.py` — async engine, `async_session_factory`, `check_connection`.
- `models.py` — SQLAlchemy ORM for the subset used by services (User, etc.).
- `__init__.py` — package marker.

## Inputs
`DATABASE_URL` from settings/env; Alembic for evolution.

## Outputs
Async sessions (`get_db`), ORM entities, schema on first container start.

## Invariants
- One schema change updates: DDL, ORM (if mapped), migration, and tests.
- `schema.sql` and `init.sql` stay byte-identical after line-ending normalization;
  `tests/test_schema.py` enforces it.
- `migrations/versions/` is tracked and has exactly one head (`0002_paper_ledger`).
- Paper state columns: `positions.side`, `entry_commission`, `margin`;
  `portfolio.initial_capital`, `margin_used`, `equity_curve`;
  `trade_history.position_side`, `entry_commission`, `exit_commission`, `exit_reason`.
- No session is shared across requests; use `get_db`.
- Money is `NUMERIC`, timestamps are timezone-aware.

## Human check
`psql $DATABASE_URL -c '\dt'`; `alembic heads` (expect one); `alembic current`;
`SELECT count(*) FROM trade_history;`.

## Tests
`tests/test_database_connection.py`, `tests/test_repository.py`,
`tests/test_schema.py`, `tests/test_paper_trading_ledger.py`.

## Known gaps
Most access is raw SQL, so the ORM covers only part of the schema. Existing databases
must run `alembic upgrade head`; `init.sql` only applies on first container start.
Migration `0002` assumes pre-existing `positions` rows are long because the old table
had no direction column; reconcile any historical shorts manually.
