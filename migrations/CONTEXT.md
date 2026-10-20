<!-- migrations/CONTEXT.md -->
# migrations/ — contract

**Purpose:** Alembic schema evolution.

## Files
- `env.py` — async engine wiring, metadata target.
- `script.py.mako` — revision template.
- `versions/` — revision files. **Currently gitignored; must be tracked (ADR/Phase 1).**
- Root `alembic.ini` — `script_location`, URL source.

## Process
1. Change `database/schema.sql` and the ORM.
2. `alembic revision --autogenerate -m "..."`.
3. Review the generated file; never hand-edit generated indexes elsewhere.
4. `alembic upgrade head` on a scratch DB; then run the suite.

## Invariants
- Exactly one head. Current repo has two `down_revision=None` revisions
  (`0001_initial_schema.py`, `89145e7e47e6_...`) — fix before adding another.
- Revision files are committed; otherwise a fresh clone cannot migrate.
- Migrations are forward-only in production; destructive changes need a plan.

## Human check
`alembic heads` (expect one), `alembic history`, `alembic upgrade head`.

## Known gaps
Versions are ignored by git; duplicate initial revisions; `schema.sql`/`init.sql` still
serve as the bootstrap path.
