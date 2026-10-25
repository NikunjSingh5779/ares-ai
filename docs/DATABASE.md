<!-- docs/DATABASE.md — conventional database reference; canonical DDL is database/schema.sql -->
# Database — ARES AI

> Canonical DDL is `database/schema.sql`. `database/init.sql` is a
> byte-identical bootstrap copy mounted by Compose; `tests/test_schema.py`
> enforces parity. Migrations are the only sanctioned way to evolve a running
> database. This file is a reference map, not a second schema.

## Engine and access

| Item | Value |
|---|---|
| Engine | PostgreSQL 16 (`postgres:16-alpine` in CI and Compose) |
| Python driver | `asyncpg` through SQLAlchemy async (`postgresql+asyncpg://`) |
| Connection setting | `DATABASE_URL` from `configs/settings.py` / environment |
| Migrations | Alembic in `migrations/versions/` |
| Bootstrap | `database/init.sql` on first postgres volume, then Alembic |
| ORM | `backend/db/models.py` (partial mapping; `app_settings` and most domain access use raw SQL) |
| Integration test | `tests/test_postgres_integration.py`, `tests/test_postgres_strategy_integration.py`, `tests/test_postgres_improvement_integration.py` |

## Tables (21)

| Group | Tables | Purpose |
|---|---|---|
| Identity & access | `users`, `accounts` | Operator account, roles, account metadata |
| Application | `app_settings` | Singleton dashboard preferences (`default_symbol`, `live_refresh_seconds`); never safety limits |
| Portfolio & execution | `portfolio`, `positions`, `orders`, `paper_trades`, `live_trades` | Balances, open/closed positions, orders, per-mode trade records |
| Signals & strategy | `signals`, `strategies`, `trade_history` | Approved/rejected decisions, strategy drafts, closed paper trades. `GET/POST/PUT /api/v1/strategies` reads/writes drafts; status and promotion fields stay server-owned. |
| Learning | `journal`, `memories`, `agent_logs`, `reflection_runs`, `improvement_records` | Decision journal, ChromaDB-linked memories, per-agent model/fallback logs, structured reflection history, and advisory improvement suggestions |
| Market & analytics | `market_data`, `metrics`, `risk_metrics`, `backtests`, `alerts` | OHLCV bars, app metrics, risk snapshots, backtest runs, alert records |

## Invariants

- **PostgreSQL is the durable paper source of truth.** The in-memory
  `PaperTradingEngine` cache is hydrated from `PaperLedgerRepository` before
  every action and is never authoritative.
- **`orders.client_order_id` is unique** through a partial unique index
  (`uq_orders_client_order_id`); duplicates return `409` and cannot create a
  second position.
- **`positions.side`** records long/short, and cost, margin, and the equity
  curve are persisted with the P1-A ledger.
- **Schema changes are atomic.** One change updates the DDL, the ORM mapping
  where applicable, a migration, and tests.
- **`app_settings` is one non-safety row.** `id` is constrained to `1`; preferences
  are JSONB. Trading caps, confidence thresholds, drawdown limits, and promotion
  gates stay in code/configuration and are exposed read-only by the settings API.
- **`init.sql` is a bootstrap copy, not a second schema.** After `init.sql`
  creates the schema, the entrypoint stamps Alembic `0001` and applies the
  idempotent `0002`–`0006` revisions (ADR-017).
- **Improvement suggestions are advisory.** `improvement_records.applied` records
  operator review only; applying a record never mutates configuration, a safety
  threshold, a position cap, or the promotion gate (ADR-022).
- **Migrations must have one head.** A split head is a bug, not a merge state.

## Migration chain

| Revision | Purpose |
|---|---|
| `0001_initial_schema.py` | Baseline for the current 21-table schema |
| `0002_paper_ledger.py` | Durable paper ledger columns, sides, cost/margin, equity curve |
| `0003_order_idempotency.py` | `client_order_id` and unique guard |
| `0004_role_hierarchy.py` | Role column and legacy-user handling |
| `0005_app_settings.py` | Singleton `app_settings` row and `updated_at` trigger |
| `0006_improvement_history.py` | `reflection_runs` and advisory `improvement_records` |

`0006` is the current head. A fresh Compose volume lands on `0001` after
`init.sql`, then applies `0002`–`0006`.

## Common commands

```powershell
# Inside the repository, with the local environment active
python -m alembic current          # applied revision
python -m alembic heads            # expect exactly one head
python -m alembic upgrade head     # apply pending migrations

# Inspect a running local database (reads POSTGRES_* from your shell/.env)
docker compose -f docker/docker-compose.yml exec postgres psql -U ares -d ares_ai -c "\dt"
```

## Integration checks

```powershell
$env:ARES_TEST_POSTGRES_URL = "postgresql+asyncpg://ares:ares_test@localhost:5432/ares_ai_test"
$env:ARES_REQUIRE_POSTGRES_INTEGRATION = "1"
python -m pytest tests/test_postgres_integration.py tests/test_postgres_strategy_integration.py tests/test_postgres_improvement_integration.py -q --no-cov
```

The CI `postgres-integration` job runs the same modules against
`postgres:16-alpine`; a missing URL becomes a hard failure when the
`ARES_REQUIRE_POSTGRES_INTEGRATION=1` flag is set.

## Read next

- Schema contract and ownership: `database/CONTEXT.md`
- Data ownership and writers: `docs/03-ARCHITECTURE.md`
- Known gaps and verified counts: `docs/02-STATUS.md`
