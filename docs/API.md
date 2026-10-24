<!-- docs/API.md — conventional API reference; live OpenAPI is served at /docs -->
# API — ARES AI

> The running application is the source of truth. Start the backend and open
> `/docs` (Swagger UI) or `/openapi.json` for request and response schemas.
> This file is a route map for reading and planning. Route implementations live
> in `backend/routers/`.

## Base URLs

| URL | Purpose |
|---|---|
| `http://localhost:8000` | Local API (default `API_HOST`/`API_PORT`) |
| `http://localhost:8080` | Optional production/nginx entry in the full root Compose stack |
| `NEXT_PUBLIC_API_URL` | Frontend client base URL (default `http://localhost:8000`) |

## Authentication

Every non-public route requires a credential:

- `X-API-Key: <API_SECRET_KEY>`, or
- `Authorization: Bearer <API_SECRET_KEY>` for API-key access, or
- `Authorization: Bearer <JWT>` returned by `POST /auth/login`.

Rules enforced today:

- An empty or default `API_SECRET_KEY` returns **503** on every non-public
  route.
- A missing credential returns **401**.
- `/execute` requires `require_trading_access`; `/live/{mode,start,stop,kill,arm}`
  require `require_live_control`.
- JWTs carry a role (`viewer`, `operator`, `admin`, `super_admin`). API keys map
  to `admin`; a missing/unknown role fails closed to `viewer`.

Public routes: `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`,
`/auth/login`.

## Route map

### Health, metrics, and docs

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | Public | 200 only when PostgreSQL, Redis, and ChromaDB answer; otherwise 503 with per-check detail |
| GET | `/metrics` | Public | Prometheus exposition mount |
| GET | `/api/v1/metrics` | Required | JSON summary of real Prometheus counters |
| GET | `/docs`, `/redoc`, `/openapi.json` | Public | Generated API documentation |

### Authentication and users

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/register` | API key | One-time bootstrap of the first operator account; role cannot be chosen by the client |
| POST | `/auth/login` | None (rate-limited) | Exchange credentials for a JWT carrying the role claim |
| GET | `/auth/verify` | Required | Verify the presented credential |
| GET | `/users/me` | Required | Current user profile |
| GET | `/users/{user_id}` | Required | Own profile, or any profile for admin roles |

### Analysis and signals

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/analyze` | Required | Run the pipeline for a symbol and return the typed result |
| GET | `/api/v1/analyze/stream` | Required | Server-Sent Events stream of pipeline progress |
| POST | `/api/v1/signal` | Required | Generate and process a trading signal through the agent path |
| GET | `/api/v1/signals/history` | Required | Recent signal history |

### Market data

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/market/candles?symbol=&interval=&limit=&source=` | Required | Read-only OHLCV candles from a free source; Binance is selected for mapped crypto symbols, Yahoo for equities; `limit` is capped at 500 |

The endpoint returns ascending, deduplicated UTC epoch timestamps and never
persists candles or makes a trading decision. Invalid intervals/sources return
`422`; an empty result is `404`; an upstream failure is `502`; a fetch timeout is
`504`.

### Chat

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/chat` | Required | Read-only assistant reply for a bounded conversation history |

The body is `{messages:[{role:"user"|"assistant",content}]}` with **1–20**
turns and **1–4000** characters per turn; the last turn must be from the user.
The response is `{reply, model, fallback_used}`. The service prepends a fixed
system prompt and runs the free-tier `chat` chain from `configs/models.yaml`.
When `LOCAL_LLM_ENABLED=true`, the separate `local_chat` entry is appended after
the remote chain, or used alone when no remote provider is configured; it is
gated to one local request per process by default. The route returns **503** if
every model fails, the local gate is busy, an error envelope is returned, or the
text is empty. It has no tools and no execution path: a reply cannot place, modify,
or cancel an order, change a trading mode, promote a strategy, or touch the kill
switch. Conversation history is client-held; there is no conversation table.

### Settings

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/settings` | Required | Effective safety limits (read-only) plus persisted dashboard preferences |
| PUT | `/api/v1/settings/preferences` | Required | Persist `default_symbol` and `live_refresh_seconds` |

The `safety` block is derived from the enforcing code and configuration
(`agents.risk`, `agents.consensus`, `configs.settings`); it is never read from
the settings table. The request body accepts only `DashboardPreferences`
(`default_symbol`, 1–20 characters, normalized uppercase; `live_refresh_seconds`,
5–30). Unknown fields, including a `safety` object, return **422**. A missing
settings row returns defaults; an unavailable store returns **503**. Preferences
are global to this single-user deployment.

### Strategy drafts

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/strategies?limit=` | Required | List saved strategy drafts, newest first; `limit` is 1-100 (default 50) |
| GET | `/api/v1/strategies/{id}` | Required | Read one saved draft |
| POST | `/api/v1/strategies` | Required | Create a draft; returns **201** |
| PUT | `/api/v1/strategies/{id}` | Required | Update a draft or paused strategy; bumps `version` |

The create/update body accepts `name`, `description`, `strategy_type`, `config`,
and `parameters` only. `status`, `live_trading_enabled`, and promotion counters
are server-owned; sending any of them returns **422**. Only `draft` and `paused`
strategies are editable, otherwise **409**. Strategy parameters are draft inputs,
not safety limits: the Risk gate and execution path still enforce the 2% position
cap, risk ceiling, drawdown, exposure, promotion gate, and kill switch. A missing
store returns **503**; a missing strategy returns **404**. The `strategies` table
already exists in the initial schema, so this slice adds no migration.

### Paper trading, portfolio, orders

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/execute` | Required + trading role | Execute an approved paper trade; requires typed Market Analyst, Quant, and Risk approvals plus `client_order_id` |
| GET | `/api/v1/portfolio` | Required | Hydrated paper portfolio summary |
| GET | `/api/v1/positions` | Required | Open/closed positions |
| GET | `/api/v1/orders` | Required | Order history |

`/execute` has no raw price or quantity fields. The server re-runs consensus,
checks the Risk approval and max position size, derives the fill from the
approved `current_price`, and caps notional at 2% of paper equity. A duplicate
`client_order_id` returns `409`; a writer-lock timeout returns `503` with
`Retry-After: 1`.

### Live trading controls

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/live/status` | Required | Mode, enabled flags, kill-switch state |
| POST | `/api/v1/live/mode` | Live-control role | Change live mode |
| POST | `/api/v1/live/start` | Live-control role | Start the live engine after all gates pass |
| POST | `/api/v1/live/stop` | Live-control role | Stop the live engine |
| POST | `/api/v1/live/kill` | Live-control role | Latch the kill switch closed |
| POST | `/api/v1/live/arm` | Live-control role | Human re-arm after a kill |
| GET | `/api/v1/live/orders` | Required | Live order records |
| GET | `/api/v1/live/positions` | Required | Live position records |
| GET | `/api/v1/live/audit` | Required | Audit trail |
| GET | `/api/v1/live/paper_record` | Required | Promotion-gate paper record |

The live controls verify the credential only, so `/live/kill` still works when
PostgreSQL is unreachable.

### Journal, memory, agents, monitoring

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/journal` | Required | Current journal entries |
| GET | `/api/v1/journal/history` | Required | Journal history |
| GET | `/api/v1/memory` | Required | Memory records |
| GET | `/api/v1/agents/status` | Required | Agent run status |
| GET | `/api/v1/agents/improvements` | Required | Improvement suggestions |
| POST | `/api/v1/agents/improvements/apply` | Required | Apply an improvement |
| GET | `/api/v1/agents/improvements/metrics` | Required | Improvement metrics |
| GET | `/api/v1/risk` | Required | Risk snapshot |
| POST | `/api/v1/backtest/run` | Required | Run a backtest |

### Research and predictions

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/predict/kronos` | Required | Optional Kronos OHLCV forecast (model downloads on first use) |
| GET | `/api/v1/research/market-context` | Required | Market context bundle for research |
| POST | `/api/v1/research/web-search` | Required | Web research through the configured free search path |
| POST | `/api/v1/collect/web-data` | Required | Collect web data into the research pipeline |

## Error conventions

- `401` — missing or invalid credential.
- `403` — valid credential without the required role.
- `409` — duplicate `client_order_id`.
- `422` — schema or approval validation failure.
- `503` — degraded dependency, default/empty API key, or paper writer-lock
  timeout (`Retry-After: 1`).

Errors are rendered by `backend/core/error_handlers.py`. Do not add ad-hoc
error shapes in routers.

## Read next

- Auth and roles: `docs/AUTH_SECURITY.md`
- Request flows: `docs/03-ARCHITECTURE.md`
- Verified endpoint checks: `docs/02-STATUS.md`
