<!-- docs/IMPLEMENTATION.md — conventional implementation map; canonical structure is 03-ARCHITECTURE.md -->
# Implementation — where the code lives

> This is a working map for changing code. Ownership rules and request flows live
> in `docs/03-ARCHITECTURE.md`; each folder's `CONTEXT.md` is the binding
> contract. Code wins over docs: verify against the source before editing.

## Top-level layout

| Path | Contents |
|---|---|
| `agents/` | LangGraph supervisor, the ten specialist agents, deterministic gates, state schemas, model client/fallback/retry/circuit-breaker |
| `backend/` | FastAPI app, routers, schemas, DB models, core security/metrics/logging, data ingestion and sources |
| `paper_trading/` | Durable paper ledger, repository, in-memory engine, background worker |
| `live_trading/` | Live engine, safety gates, audit trail, exchange connectors |
| `backtesting/` | Pure-Python backtest engine |
| `database/` | Canonical DDL (`schema.sql`), Compose bootstrap copy (`init.sql`), async connection factory |
| `migrations/` | Alembic environment and `0001`–`0005` revisions |
| `configs/` | Settings loader and `models.yaml` roster/fallback chains |
| `frontend/` | Next.js dashboard (App Router) |
| `landing/` | Astro marketing page |
| `scripts/` | Operational scripts: pipeline simulation, free-model validation, live runner helpers |
| `tests/` | Pytest suite, mirroring module paths |
| `docker/` | Compose variants, Dockerfiles, entrypoint, monitoring config |

## Request flow in one screen

```text
Browser / API client
  -> backend/main.py (security headers, rate limit, CORS, router mount)
  -> backend/routers/<domain>.py (validate, delegate)
  -> agents/supervisor.py (LangGraph; typed state slices)
  -> agents/consensus.py + agents/risk.py (deterministic gates)
  -> paper_trading/ or live_trading/ (domain decisions)
  -> PostgreSQL / Redis / ChromaDB (durable state, cache, memory)
  -> typed response or SSE stream
```

- **Analysis:** `backend/routers/analysis.py` -> `agents/supervisor.py` ->
  `PIPELINE_ORDER`. The module-global `_last_state` caches the last run and is
  a known isolation gap (see `docs/02-STATUS.md`).
- **Paper execution:** `backend/routers/trading.py` -> `PaperTradingLedger` ->
  `PaperLedgerRepository` -> PostgreSQL, with the in-memory engine used only
  as a rehydrated cache.
- **Live execution:** `agents/execution.py` -> `LiveTradingEngine.execute_signal`
  -> fail-closed safety gates -> exchange connector -> `OrderAuditor`. There is
  exactly one production `create_order` call site.
- **Backtest:** `backend/routers/backtest.py` -> `backtesting/engine.py`.
- **Settings:** `backend/routers/settings.py` -> `settings_service` -> singleton
  `app_settings` JSONB row. The safety block is computed from `agents.risk`,
  `agents.consensus`, and `configs.settings`; it never comes from the table.
- **Strategy drafts:** `backend/routers/strategies.py` -> `strategy_service` ->
  the existing `strategies` table. Create lands as `draft`; only draft/paused rows
  are editable, and status/live/promotion fields stay server-owned.

## Where to make a change

| Change | Start here | Also update |
|---|---|---|
| Agent behavior, prompt, schema | `agents/<agent>.py`, `agents/state.py` | `agents/CONTEXT.md`, tests |
| New API endpoint | `backend/routers/<domain>.py` | `backend/schemas/`, `frontend/src/lib/api.ts`, `frontend/src/types/api.ts`, `docs/API.md` |
| Paper fill, PnL, fees, positions | `paper_trading/engine.py`, `paper_trading/ledger.py` | `paper_trading/CONTEXT.md`, ledger tests |
| Live gate, kill switch, orders | `live_trading/safety.py`, `live_trading/engine.py` | `live_trading/CONTEXT.md`, security tests |
| Backtest metric | `backtesting/engine.py` | `backtesting/CONTEXT.md`, tests |
| DB column/table | `database/schema.sql`, ORM mapping if used | migration, `database/init.sql`, `tests/test_schema.py` |
| Model roster/fallback | `configs/models.yaml` | `configs/CONTEXT.md`, `scripts/test_free_models.py` |
| Dashboard page | `frontend/src/app/<page>/page.tsx` | `frontend/src/lib/api.ts`, types, `frontend/CONTEXT.md` |
| CI/CD or container | `.github/workflows/ci.yml`, `docker/` | `docker/CONTEXT.md`, `docs/DEPLOYMENT.md` |

## Placement rules (MVC + ICM)

- **Model:** `backend/schemas/`, `backend/db/models.py`, `frontend/src/types/api.ts`,
  `agents/state.py`.
- **View:** response models, `/docs`, `frontend/src/app/**/page.tsx`,
  `frontend/src/components/`.
- **Controller:** `backend/routers/`, `frontend/src/lib/api.ts`,
  `frontend/src/lib/usePipelinePolling.ts`, `agents/<agent>.py`.
- **Domain/service:** `paper_trading/`, `live_trading/`, `backtesting/`,
  `agents/consensus.py`, `agents/risk.py`.
- **Factory/reference:** `configs/`, `docker/`, `.github/`, `docs/design.md`.

Rule of thumb: **routers translate, domain modules decide, agents interpret.**
A router must not own portfolio state or call an exchange directly.

## Build and run

```powershell
uv sync --locked --all-extras --dev
python -m pytest tests/test_icm_structure.py -q --no-cov
python -m pytest tests/ -q
ruff check .
ruff format --check .
mypy .
```

Frontend:

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm build
```

Full local stack:

```powershell
docker compose --env-file .env -f docker/docker-compose.yml up -d
```

## Read next

- Architecture and data ownership: `docs/03-ARCHITECTURE.md`
- Setup: `docs/SETUP.md`
- Testing: `docs/TESTING.md`
- Debugging: `docs/DEBUGGING.md`
