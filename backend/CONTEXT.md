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
| Core | `core/` — `dependencies` (auth/roles), `roles`, `rate_limit`, `security` (headers/JWT), `metrics`, `logging`, `error_handlers`, `login_rate_limit` |
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
- Trading/live-control routes also require a role: `/execute` uses
  `require_trading_access`; `/live/{mode,start,stop,kill,arm}` use
  `require_live_control`. `viewer` is read-only; `operator`/`admin`/`super_admin` may
  trade. JWTs carry the `role` claim minted at login; API keys map to `admin`; tokens
  without a role are read-only. Role checks verify the credential only and do not query
  PostgreSQL, so the kill switch remains usable during a database outage.

## Dependency direction
`main → routers → services/domain → db/data`. Never the reverse; `routers/` must not be
imported by domain packages.

## Human check
- `GET /health` returns 200 only when DB/Redis/Chroma answer; otherwise 503 with
  per-check detail. `GET /metrics` is the public Prometheus exposition;
  `/api/v1/metrics` is the authenticated JSON counter summary.
- `GET /docs` shows the route and schema.
- Any `/api/v1/*` call without a key returns 401; with the default key returns 503.
- A viewer JWT gets 403 on `/execute` and every `/live` control.
- `pytest tests/test_analysis_router.py tests/test_security/ -q`

## Paper trading boundary
`trading.py` keeps a process-local `PaperTradingEngine` cache but coordinates every
read/write through `paper_trading.ledger.PaperTradingLedger`; PostgreSQL is the durable
source. `/portfolio`, `/positions`, and `/orders` hydrate before responding and return
503 when the ledger is unavailable. `/execute` accepts only an `ExecuteTradeRequest`
containing typed Market Analyst, Quant, and Risk approvals plus a required
`client_order_id`. The router re-runs consensus, checks Risk approval/score, derives the
fill from the approved `current_price`, derives quantity from
`risk.max_position_size`, and caps notional at 2% of paper equity. It has no raw
price/quantity fields and no manual bypass. A duplicate `client_order_id` returns 409;
a writer-lock timeout returns 503 with `Retry-After: 1`; other
ledger failures return 503. The normal generated-trade path remains `/signal`.

## Known gaps
- `/execute` trusts the authenticated caller's agent payload; there is no signed or
  expiring signal token. The API key remains the trust boundary.
- The paper writer lock is database-wide rather than per account; writes serialize
  globally, which is fine for a single seeded paper account.
- `analysis.py` still owns the module-global `_last_state`; `/agents/status` and `/risk`
  read it, while `/api/v1/metrics` is now registry-backed.
- Prometheus counters are process-local; a multi-worker API would need multiprocess
  registry aggregation. Compose runs one uvicorn worker.
- Role changes take effect on the next login because the role is a JWT claim; there is no
  revocation list. API-key holders always map to `admin`.
