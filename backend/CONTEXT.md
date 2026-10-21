<!-- backend/CONTEXT.md -->
# backend/ — contract

**Purpose:** the HTTP boundary, data ingestion, auth/security, and metrics.
Controllers translate; they must not own domain state.

## Layout (MVC)
| Role | Path |
|---|---|
| Controllers | `routers/` — `analysis`, `trading`, `live`, `agents`, `journal`, `monitoring`, `backtest`, `predictions`, `auth`, `users` |
| Models | `schemas/` (API), `db/models.py` (ORM) |
| Views | JSON responses + OpenAPI `/docs`; SSE in `analysis.stream_analysis` |
| Core | `core/` — `dependencies` (auth), `rate_limit`, `security` (headers/JWT), `metrics`, `logging`, `error_handlers`, `login_rate_limit` |
| Data | `data/` — `ingestor`, `models`, `sources/` (yahoo, binance, coingecko, web_search) |
| Services | `services/` — `user_service` |
| App | `main.py` — lifespan, middleware, router registration, `/health` |

## Inputs
HTTP requests, DB sessions, Redis, ChromaDB; upstream market APIs.

## Outputs
JSON/SSE responses, Prometheus metrics at `/metrics`, health at `/health`, DB writes.

## Invariants
- Routers validate and delegate; domain rules live in agents/domain modules.
- No model IDs or secrets in code; use `configs.settings`.
- Errors use the handlers in `core/error_handlers.py`, not `print`.
- New endpoints are documented and added to the frontend client or they do not exist.
- Every domain router is mounted with `Depends(verify_auth)` in `main.py`; the auth
  router alone is mounted publicly. `/auth/login` is the only credential-free auth
  endpoint; `/auth/register` requires the operator API key and cannot set `role`;
  `/auth/verify` declares `verify_auth` itself.

## Dependency direction
`main → routers → services/domain → db/data`. Never the reverse; `routers/` must not be
imported by domain packages.

## Human check
- `GET /health` reports DB/Redis/Chroma reachability (public).
- `GET /docs` shows the route and schema.
- Any `/api/v1/*` call without a key returns 401; with the default key returns 503.
- `pytest tests/test_analysis_router.py tests/test_security/ -q`

## Paper trading boundary
`trading.py` keeps a process-local `PaperTradingEngine` cache but coordinates every
read/write through `paper_trading.ledger.PaperTradingLedger`; PostgreSQL is the durable
source. `/portfolio`, `/positions`, and `/orders` hydrate before responding and return
503 when the ledger is unavailable. `/execute` goes through the ledger and returns 503
if the paper account is not seeded, rather than accepting an unpersisted trade.

## Known gaps
- `/execute` accepts a raw body and bypasses consensus/risk; it is paper-only but can
  distort promotion statistics until P1-B.
- `analysis.py` still owns the module-global `_last_state`.
- `/health` returns 200 even when degraded; `/metrics` product endpoint is derived from
  the last run, not Prometheus counters.
- No role-based authorization: any valid API key/JWT reaches trading and live controls.
