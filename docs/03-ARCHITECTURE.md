<!-- docs/03-ARCHITECTURE.md -->
# Architecture — layers, flows, and where code belongs

ICM owns navigation (this file, `AGENTS.md`, `CONTEXT.md`). MVC owns placement
(`models/`, `views/`, `controllers/` equivalents). This document **maps the existing
layout honestly** — it does not rename folders. See ADR-002.

## 1. Runtime layers

```
Presentation   frontend/ (Next.js app router)      landing/ (Astro)
     │
API gateway    backend/main.py + backend/routers/  (FastAPI, /api/v1)
     │
Orchestration  agents/supervisor.py (LangGraph)     scripts/run_live.py (runner)
     │
Agents         agents/*.py       deterministic gates: consensus.py, risk.py
     │
Execution      paper_trading/    live_trading/    backtesting/
     │
Data           backend/data/     database/        configs/
     │
Monitoring     backend/core/metrics.py   docker/monitoring/ (Prometheus + Grafana)
```

## 2. Request flows

**Analysis** (`POST /api/v1/analyze`, `GET /analyze/stream`, `POST /signal`)
`backend/routers/analysis.py` builds a `Supervisor`, runs the LangGraph in
`agents/supervisor.py`, and stores each result in a bounded per-session state
store (`backend/services/analysis_control.py`). The store keeps the most
recently started run as the dashboard default and lets API callers read a
specific `session_id`. A process-wide gate allows one pipeline at a time by
default, rejects extra starts with **429** instead of queueing unbounded
background tasks, caps starts per rolling hour, and applies a stage-start
deadline that is cleared once execution begins. The graph order is
`PIPELINE_ORDER`; consensus and risk are deterministic nodes, not LLM calls.

**Chat** (`POST /api/v1/chat`)
`backend/routers/chat.py` validates a bounded history, then
`backend/services/chat_service.py` prepends a fixed system prompt and runs the
free-tier `chat` chain through `ModelRouter`. With `LOCAL_LLM_ENABLED=true`, the
service appends the separate `local_chat` entry after the remote chain, or uses it
alone when no remote provider is configured; the opt-in `local/` call shares one
process-wide gate (default one request) and fails closed when busy. History is
client-held and the service is stateless; it has no tools and no execution path.
An exhausted chain, an error envelope, or empty text returns 503 rather than a
fabricated reply.

**Paper execution** (`POST /api/v1/execute`, `POST /api/v1/signal`, `scripts/run_live.py`)
The normal pipeline path is `ExecutionAgent` (`agents/execution.py`) → `PaperTradingLedger`
(`paper_trading/ledger.py`). The API path is different: `/execute` accepts a typed
`ExecuteTradeRequest` containing Market Analyst, Quant, and Risk outputs, a
`client_order_id`, and a short-lived signed `approval_token`. `/signal` with
`execute=false` runs the pipeline through risk, skips execution, and issues that token
bound to the symbol, side, and payload digest; `/execute` verifies it before doing any
work. The router then re-runs `ConsensusEngine.evaluate`, checks Risk's approval
and score, derives the fill from the approved `current_price`, derives quantity from
`risk.max_position_size`, and caps notional at 2% of paper equity. It does not accept
caller-supplied price or quantity and has no manual bypass.

The ledger refreshes the in-memory `PaperTradingEngine` cache from
`PaperLedgerRepository` (`paper_trading/repository.py`), lets the engine fill with
configured commission and adverse slippage, then writes the position, orders, trade
history, and portfolio in one PostgreSQL transaction. Every write runs inside two locks:
an in-process `asyncio.Lock` around the shared cache, and a PostgreSQL
transaction-scoped advisory lock (`pg_try_advisory_xact_lock`) held across
hydrate → mutate → persist. The API, worker, and runner therefore serialize instead of
overwriting each other's committed state; a writer that cannot get the lock within
`PAPER_TRADING_WRITER_LOCK_TIMEOUT_SECONDS` fails with 503 instead of mutating stale
state. `client_order_id` is checked before
mutation and protected by a partial unique index; duplicates return 409 and never create a
second position. A failed write or duplicate restores the pre-action engine snapshot; an
accepted fill with no seeded paper account is rejected instead of being kept only in
memory. The engine marks open positions on every bar and reports equity-based PnL; shorts
credit proceeds and report 100% notional margin. `paper_trading/worker.py` and the runner
poll loop process candles through the same ledger, so stop-loss/take-profit closures and
marks are durable. API reads hydrate from the ledger before returning.

**Live execution** (`/api/v1/live/*`, `scripts/run_live.py`)
`ExecutionAgent` → `LiveTradingEngine.execute_signal()` → safety gates
(fail-closed kill switch with a shared Redis arm epoch, mode, promotion, exchange) →
exchange connector → `OrderAuditor`. The engine also refuses to start or execute when
`LIVE_TRADING_ENABLED=false`; this is the default. There is exactly one
production `exchange.create_order` call site: `live_trading/engine.py`.

**Authentication** (every non-public route)
`backend/main.py` mounts each domain router with `Depends(verify_auth)`.
`verify_auth` accepts `X-API-Key` (or a Bearer token containing the same key),
or a JWT only when `JWT_SECRET_KEY` is configured. An empty/default
`API_SECRET_KEY` returns 503. Public: `/health`, `/metrics`, `/docs`,
`/redoc`, `/openapi.json`, `/auth/login`. `/auth/register` is a one-time
bootstrap that requires the operator's API key; `/auth/verify` also requires a
credential. The frontend stores the key in `sessionStorage` and `AuthGate`
redirects to `/login` when absent.

`/execute` and the live controls (`mode`, `start`, `stop`, `kill`, `arm`) add a
second gate: `require_trading_access` / `require_live_control` in
`backend/core/dependencies.py`. JWTs carry the role (`viewer`, `operator`,
`admin`, `super_admin`) minted at login; API keys map to `admin`; a missing or
unknown role fails closed to `viewer`. The gate verifies the credential only, so
`/live/kill` still works when PostgreSQL is unreachable.

**Health and metrics** (`GET /health`, `GET /metrics`, `GET /api/v1/metrics`)
`/health` probes PostgreSQL, Redis, and ChromaDB and returns **200** only when all three
answer; otherwise it returns **503** with per-check detail, which is the signal Compose
healthchecks consume. `/metrics` is the public Prometheus exposition mount. The
authenticated `/api/v1/metrics` is a JSON summary of the same counters (HTTP requests,
agent runs/errors/fallbacks, analysis starts/in-flight, live orders, kill-switch
state); it does not read the pipeline state store. Counters are process-local and
cumulative since the API process started.

**Backtest** (`POST /api/v1/backtest/run`)
`backend/routers/backtest.py` → `backtesting/engine.py` (pure Python; commission and
slippage modelled; entry at next candle open when no fixed price).

## 3. MVC mapping (existing paths)

| Concern | Backend | Frontend | Agents |
|---|---|---|---|
| **Model** — data shape/rules | `backend/schemas/`, `backend/db/models.py` | `frontend/src/types/api.ts` | `agents/state.py` (Pydantic slices) |
| **View** — what is returned/shown | response models + `/docs` | `frontend/src/app/**/page.tsx`, `frontend/src/components/` | typed output schemas rendered by `/api/v1/agents/status` |
| **Controller** — request/action logic | `backend/routers/<domain>.py` | `frontend/src/lib/api.ts`, `frontend/src/lib/usePipelinePolling.ts` | `agents/<agent>.py`, `agents/supervisor.py` |
| **Domain/service** — rules that outlive a request | `paper_trading/`, `live_trading/`, `backtesting/`, `backend/services/` | — | `agents/consensus.py`, `agents/risk.py`, `agents/improvement.py` |
| **Factory/reference** — stable config | `configs/`, `docker/`, `.github/` | `docs/design.md` | `configs/models.yaml` |
| **Product/output** — per-run artifacts | `logs/`, `htmlcov/` | build output | `agent_logs`, `journal`, `memories` tables |

Rule of thumb: **routers translate, domain modules decide, agents interpret.**
A router may validate and delegate; it must not own portfolio state or exchange calls.

## 4. Data ownership (current)

| Data | Current home | Writers | Risk |
|---|---|---|---|
| Paper portfolio/positions | PostgreSQL `portfolio` and `positions` | `PaperTradingLedger` through `PaperLedgerRepository`, used by API, worker, and runner | writes serialize on an advisory lock; `client_order_id` blocks duplicate requests |
| Paper cache | in-memory `PaperTradingEngine` | hydrated from the ledger before every action; snapshot-restored on write failure | process-local cache only; never the source of truth |
| Closed paper trades | `trade_history` table | ledger closures and execution-agent fallback | promotion gate reads this table |
| Pipeline result | bounded per-session `AnalysisStateStore` (`backend/services/analysis_control.py`) | `/analyze`, `/analyze/stream`, `/signal` | latest-started run by default; `session_id` selects one run; capacity-bounded; process-local |
| Live orders | exchange + `OrderAuditor` | `LiveTradingEngine.execute_signal` only | single path; kill switch is shared Redis state with a shared arm epoch |
| Model roster | `configs/models.yaml` | — | validated free IDs + universal fallback appended by `AgentModelConfig` |
| Dashboard preferences | singleton `app_settings` JSONB row | `settings_service` through `PUT /api/v1/settings/preferences` | non-safety only; safety limits are computed from `agents.risk`/`agents.consensus`/`configs.settings` (ADR-018) |
| Strategy drafts | PostgreSQL `strategies` | `strategy_service` through `/api/v1/strategies` | draft/paused edits only; status, live enablement, and promotion counters are server-owned and never written by this surface |
| Reflection/improvement history | PostgreSQL `reflection_runs`, `improvement_records` | `improvement_service` through the best-effort supervisor post-run hook and `/api/v1/agents/improvements` | advisory only; applying a record never mutates configuration or a safety limit; a history outage leaves the pipeline result unchanged |
| Schema | `database/schema.sql`, `database/init.sql`, tracked `migrations/versions/` | Alembic / Compose bootstrap | `init.sql` is a byte-identical bootstrap copy; `0001`–`0006` are the migration chain; a fresh volume stamps `0001` after `init.sql`, then applies the idempotent later revisions (ADR-017) |

ADR-005 is implemented for paper state; ADR-014 adds the approved `/execute` contract and
client-order idempotency; ADR-015 serializes paper writers across processes; ADR-017 fixes
the Compose bootstrap and Chroma version handshake; ADR-018 keeps dashboard preferences
durable while safety limits remain read-only; ADR-022 persists improvement history while
keeping suggestions advisory. ADR-023 bounds analysis runs and replaces the
single pipeline global with a per-session store; the remaining ownership issue is
live-order state, not the pipeline result.

## 5. Dependency rules (target, enforced by review)

1. `frontend/src/app/**` → `frontend/src/lib/api.ts` only. No direct `fetch`, no mock data in pages.
2. `backend/routers/**` → `backend/schemas`, `backend/services`, domain modules. Never import `frontend/`.
3. `agents/**` → domain modules and `backend/` utilities. Deterministic gates (`consensus`, `risk`) never call an LLM.
4. `paper_trading/`, `live_trading/`, `backtesting/` must not import `backend/routers/`.
5. Model IDs only in `configs/models.yaml`; secrets only from settings/env.
6. Tests mirror the module path: `tests/test_<area>/test_<module>.py`.

## 6. Folder contracts

Every working folder has a `CONTEXT.md` with inputs, process, outputs, human check.
Read the contract before the code; update it when the folder’s job changes.
