<!-- backend/CONTEXT.md -->
# backend/ — contract

**Purpose:** the HTTP boundary, data ingestion, auth/security, and metrics.
Controllers translate; they must not own domain state.

## Layout (MVC)
| Role | Path |
|---|---|
| Controllers | `routers/` — `analysis`, `trading`, `live`, `agents`, `journal`, `monitoring`, `backtest`, `predictions`, `market`, `settings`, `strategies`, `chat`, `auth`, `users` |
| Models | `schemas/` (API), `db/models.py` (ORM) |
| Views | JSON responses + OpenAPI `/docs`; SSE in `analysis.stream_analysis` |
| Core | `core/` — `dependencies` (auth/roles), `roles`, `rate_limit`, `security` (headers/JWT), `metrics`, `logging`, `error_handlers`, `login_rate_limit` |
| Data | `data/` — `ingestor`, `models`, `sources/` (yahoo, binance, coingecko, web_search) |
| Services | `services/` — `user_service`, `settings_service`, `strategy_service`, `chat_service` |
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

## Market data boundary
`GET /api/v1/market/candles` is a read-only view over the free source registry in
`backend/data/sources/`. It selects Binance for symbols in `SYMBOL_TO_BINANCE` and
Yahoo otherwise, accepts an explicit `source`, validates the interval/limit, closes
the upstream client in `finally`, and returns ascending deduplicated UTC epoch
candles. It never persists candles and never makes a trading decision. Upstream
failures are `502`, timeouts are `504`, and an empty result is `404`.

## Settings boundary
`GET /api/v1/settings` returns a **read-only** `SafetyLimits` block derived from
`agents.risk`, `agents.consensus`, and `configs.settings`, plus the persisted
`DashboardPreferences`. `PUT /api/v1/settings/preferences` accepts only
`default_symbol` and `live_refresh_seconds`; `DashboardPreferences` uses
`extra="forbid"`, so a `safety` object or any limit override is **422** before the
service runs. `settings_service` reads/upserts the singleton `app_settings` row
(JSONB) and merges defaults for forward compatibility. Preferences are global to
the single-user deployment and are never read by the risk, consensus, execution,
or live safety paths. An unavailable store returns **503**; a missing row returns
defaults.

## Strategy draft boundary
`GET/POST /api/v1/strategies` and `GET/PUT /api/v1/strategies/{id}` expose the
existing `strategies` table as a draft configuration surface. `StrategyCreate` and
`StrategyUpdate` use `extra="forbid"`, so `status`, `live_trading_enabled`, and the
promotion counters are **422** and never written; create lands as the table default
`draft`. Only `draft` and `paused` rows are editable (**409** otherwise), and an
update bumps `version` without touching lifecycle fields. The draft `parameters`
are not a safety override: the Risk, consensus, promotion, execution, and kill-switch
paths remain authoritative. No schema or migration change was needed because the
table exists in the initial schema. Missing rows are **404**; store failures are
**503**.

## Chat boundary
`POST /api/v1/chat` is a **read-only** conversational endpoint mounted behind
`verify_auth`. `ChatRequest` accepts 1–20 turns of 1–4000 characters and requires
the last turn to be from the user; unknown fields are **422**. History is
client-held; there is no conversation table or server-side memory. The service
prepends a fixed system prompt, runs the free-tier `chat` chain from
`configs/models.yaml` through the standard fallback router, and returns
`{reply, model, fallback_used}`. It has no tools and no execution path, so it
cannot place/modify/cancel orders, change modes, promote a strategy, or touch the
kill switch. An exhausted chain, an error envelope (including the NoOp client),
or empty text returns **503**; the API never fabricates a reply.

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
- Dashboard preferences are one global `app_settings` row, not per user. The shared API
  key has no user row, and the deployment is single-user; multi-user needs an explicit
  user-scoped store.
- Chat depends on live free-tier model availability; the configured chain is probed
  manually, not in CI, and an exhausted chain fails closed with **503**.
