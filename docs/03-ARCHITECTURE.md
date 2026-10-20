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
Monitoring     backend/core/metrics.py   docker/prometheus   docker/grafana
```

## 2. Request flows

**Analysis** (`POST /api/v1/analyze`, `GET /analyze/stream`, `POST /signal`)
`backend/routers/analysis.py` builds a `Supervisor`, runs the LangGraph in
`agents/supervisor.py`, stores the result in the module-global `_last_state`, and
returns or streams it. The graph order is `PIPELINE_ORDER`; consensus and risk are
deterministic nodes, not LLM calls.

**Paper execution** (`POST /api/v1/execute`, `scripts/run_live.py`)
`ExecutionAgent` (`agents/execution.py`) asks `PaperTradingEngine`
(`paper_trading/engine.py`) to fill with configured commission and adverse slippage,
then persists the engine's actual fill/quantity via raw SQL. The engine marks open
positions on every bar and reports equity-based PnL; shorts credit proceeds and report
100% notional margin. The runner’s poll loop marks candles, checks stop-loss/take-profit,
writes `trade_history`, and mirrors the engine snapshot to the DB portfolio
(`paper_trading/worker.py`).

**Live execution** (`/api/v1/live/*`, `scripts/run_live.py`)
`ExecutionAgent` → `LiveTradingEngine.execute_signal()` → safety gates
(fail-closed kill switch, mode, promotion, exchange) → exchange connector →
`OrderAuditor`. The engine also refuses to start or execute when
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

**Backtest** (`POST /api/v1/backtest/run`)
`backend/routers/backtest.py` → `backtesting/engine.py` (pure Python; commission and
slippage modelled; entry at next candle open when no fixed price).

## 3. MVC mapping (existing paths)

| Concern | Backend | Frontend | Agents |
|---|---|---|---|
| **Model** — data shape/rules | `backend/schemas/`, `backend/db/models.py` | `frontend/src/types/api.ts` | `agents/state.py` (Pydantic slices) |
| **View** — what is returned/shown | response models + `/docs` | `frontend/src/app/**/page.tsx`, `frontend/src/components/` | typed output schemas rendered by `/api/v1/agents/status` |
| **Controller** — request/action logic | `backend/routers/<domain>.py` | `frontend/src/lib/api.ts`, `frontend/src/lib/usePipelinePolling.ts` | `agents/<agent>.py`, `agents/supervisor.py` |
| **Domain/service** — rules that outlive a request | `paper_trading/`, `live_trading/`, `backtesting/` | — | `agents/consensus.py`, `agents/risk.py`, `agents/improvement.py` |
| **Factory/reference** — stable config | `configs/`, `docker/`, `.github/` | `docs/design.md` | `configs/models.yaml` |
| **Product/output** — per-run artifacts | `logs/`, `htmlcov/` | build output | `agent_logs`, `journal`, `memories` tables |

Rule of thumb: **routers translate, domain modules decide, agents interpret.**
A router may validate and delegate; it must not own portfolio state or exchange calls.

## 4. Data ownership (current, not target)

| Data | Current home | Also written by | Risk |
|---|---|---|---|
| Paper portfolio/positions | in-memory `PaperTradingEngine` singleton | runner process has a second engine; DB `portfolio`/`positions` are projections | restart loses state; UI and DB disagree |
| Closed paper trades | `trade_history` table | worker SL/TP closures + agent reversals | promotion gate reads this table; `positions` has no side column |
| Pipeline result | module-global `_last_state` | every `/analyze` call | last writer wins; no per-user isolation |
| Live orders | exchange + `OrderAuditor` | `LiveTradingEngine.execute_signal` only | single path; kill switch is shared Redis state |
| Model roster | `configs/models.yaml` | — | validated free IDs + universal fallback appended by `AgentModelConfig` |
| Schema | `database/schema.sql`, `database/init.sql`, `migrations/` | — | three sources; migrations untracked |

Target ownership is decided in ADR-005/006 and implemented in Phase 1 of
`05-NEXT.md`. Until then, treat the table above as the truth.

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
