<!-- migrations/CONTEXT.md -->
# migrations/ — contract

**Purpose:** Alembic schema evolution.

## Files
- `env.py` — async engine wiring, metadata target.
- `script.py.mako` — revision template.
- `versions/0001_initial_schema.py` — base schema; executes `database/schema.sql`
  through a splitter that preserves single/double quotes and dollar-quoted PL/pgSQL.
- `versions/0002_paper_ledger.py` — durable paper-ledger columns and side backfill;
  idempotent because a fresh `0001` already executes the current schema.
- `versions/0003_order_idempotency.py` — `orders.client_order_id` and its partial unique
  index; idempotent for the same reason.
- `versions/0004_role_hierarchy.py` — finds the existing `users.role` check dynamically,
  rewrites `user` → `operator`, allows `viewer`/`operator`, and sets the default to
  `viewer`; idempotent for the same reason.
- Root `alembic.ini` — `script_location`, URL source.

## Process
1. Change `database/schema.sql` and the ORM/raw SQL owners.
2. Add a forward revision; do not rewrite an applied production revision.
3. For a fresh database, `0001` applies the current `schema.sql`; keep follow-up
   revisions idempotent (use `IF NOT EXISTS` / guarded constraints).
4. Run `alembic upgrade head` on a scratch PostgreSQL 16 database, then run the suite.

## Invariants
- Exactly one head: `0004_role_hierarchy` revises `0003_order_idempotency`, which revises
  `0002_paper_ledger`, which revises `0001_initial_schema`.
- Revision files are committed; otherwise a fresh clone cannot migrate.
- `database/schema.sql` and `database/init.sql` remain byte-identical.
- Migrations are forward-only in production; destructive changes need a plan.
- `0002` backfills `trade_history.position_side='short'` for rows whose entry side is
  `sell`. Old `positions` rows have no direction and default to long. `0003` adds the
  per-account client-order uniqueness guard; `0004` migrates the role vocabulary.
  Existing databases need `upgrade head` (back up first).

## Human check
`alembic heads` (expect one), `alembic history`, `alembic upgrade head`, then
`alembic current`. On an existing deployment, back up before upgrading.

## Known gaps
Pre-existing short positions cannot be inferred from the old schema and must be
reconciled manually. There is no automated PostgreSQL migration job in CI yet.
