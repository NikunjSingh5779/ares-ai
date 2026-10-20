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
- No session is shared across requests; use `get_db`.
- Money is `NUMERIC`, timestamps are timezone-aware.

## Human check
`psql $DATABASE_URL -c '\dt'`; `SELECT count(*) FROM paper_trades;`.

## Tests
`tests/test_database_connection.py`, `tests/test_repository.py`.

## Known gaps
Schema exists in three places (`schema.sql`, `init.sql`, untracked Alembic versions);
most access is raw SQL, so the ORM covers only part of the schema.
