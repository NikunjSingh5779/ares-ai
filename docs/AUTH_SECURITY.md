<!-- docs/AUTH_SECURITY.md — conventional security guide; canonical rules are 01-SPEC.md and ADRs 009-011, 016 -->
# Auth and security — ARES AI

> The safety rules are non-negotiable: see `docs/01-SPEC.md`. Structural
> rationale is in `docs/04-DECISIONS.md` (ADR-009 auth, ADR-010 kill switch,
> ADR-011 live opt-in, ADR-016 roles, ADR-024 shared arm epoch, ADR-025 signed
> approvals). This file explains the current implementation and its known limits.

## Authentication

Every non-public FastAPI router is mounted with `Depends(verify_auth)` in
`backend/main.py`. The accepted credentials are:

1. `X-API-Key: <API_SECRET_KEY>`
2. `Authorization: Bearer <API_SECRET_KEY>`
3. `Authorization: Bearer <JWT>` from `POST /auth/login`

An empty or default `API_SECRET_KEY` is rejected with **503** on every
non-public route. A missing or invalid credential returns **401**.

Public routes are deliberately limited to `/health`, `/metrics`, `/docs`,
`/redoc`, `/openapi.json`, and `/auth/login`. `/auth/register` is a one-time
bootstrap that requires the operator API key; the client cannot choose its own
role.

## Roles

| Role | Capabilities |
|---|---|
| `viewer` | Read-only API access; cannot execute trades or change live controls |
| `operator` | Trading access and live controls |
| `admin` | Operator capabilities plus administrative access |
| `super_admin` | Full administrative access |

- JWTs carry the `role` claim minted at login.
- API keys map to `admin`.
- A missing or unknown role fails closed to `viewer`.
- `/execute` uses `require_trading_access`; `/live/{mode,start,stop,kill,arm}`
  use `require_live_control`.
- Role checks verify the credential only and do not query PostgreSQL, so
  `/live/kill` remains usable during a database outage.
- Role changes take effect on the next login; there is no token revocation
  list.

## Signed trade approvals

`/execute` is a second gate on top of authentication: a credential alone cannot
execute a trade. The caller must present an `approval_token` minted by
`POST /signal` with `execute=false` after the pipeline approved a long or short
signal.

- The token is a JWT signed with `JWT_SECRET_KEY` (HS256 by default) and carries
  `typ=trade_approval`, `iss=ares-ai`, `aud=paper-execute`, `iat`, `exp`, `jti`,
  `symbol`, `side`, and `approval_hash`.
- `approval_hash` is SHA-256 over canonical sorted-key compact JSON of the typed
  Market Analyst/Quant/Risk payload. `/execute` recomputes it from the submitted
  payload and compares in constant time.
- Lifetime is `APPROVAL_TOKEN_EXPIRE_MINUTES` (default 5, bounded 1–30).
  Verification rejects expired tokens before any ledger work.
- A token for a different symbol, side, or payload is rejected even though the
  signature is valid.
- Issuance and verification refuse an empty or shipped-default `JWT_SECRET_KEY`.
  `/signal` returns **503** rather than minting a forgeable approval.
- Login access tokens do not carry `typ=trade_approval`, so they cannot be
  replayed against `/execute`; approval tokens carry no `role` claim and are not
  accepted by normal authenticated routes.

The token is a short-lived **bearer capability, not a single-use nonce**. Anyone
holding it within the expiry window can submit the bound payload. Treat it like a
credential, do not log it, and mint a fresh one per execution attempt. Duplicate
order protection remains `client_order_id`, which is unique per paper account.

## Secrets

- `.env` is local only and ignored by git. `.env.example` is the template.
- Production startup rejects the literal `changeme_in_production` for the API
  key, JWT secret, and database password.
- Generate the API key with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- Never print, screenshot, paste, or commit `.env`; never send secrets to a web
  search, MCP server, or third-party fetch.
- Exchange and model-provider keys belong in environment variables or a secret
  manager, not in source, docs, tests, or logs.
- `.mcp.json` contains only local placeholder credentials; do not put a real
  password in it. See `docs/MCP.md`.

## Transport and request hardening

- `SecurityHeadersMiddleware` adds HSTS, `X-Content-Type-Options`, and related
  headers (`backend/core/security.py`).
- CORS is configured from `API_CORS_ORIGINS`; default local origin is
  `http://localhost:3000`.
- A general API rate limit is configured with `API_RATE_LIMIT_PER_MINUTE`.
- Login has a two-tier sliding-window brute-force limiter
  (`backend/core/login_rate_limit.py`), keyed by hashed email+IP and by IP.
- `TRUSTED_PROXIES` should be set only when a trusted reverse proxy supplies
  `X-Forwarded-For`.

## Live-trading safety gates

Live trading is opt-in at every layer:

1. `LIVE_TRADING_ENABLED=false` by default; the engine refuses to start or
   execute otherwise.
2. Human-approval mode is the default for every new strategy/account.
3. The paper-trading promotion gate must be met before autonomous mode.
4. The kill switch latches closed and requires human re-arm; `arm()` publishes an
   `arm:` epoch token in shared Redis, so one human action clears every process that
   had observed the shared state. Recovery, a missing token, or a republished
   baseline never clears a latch by itself.
5. Every live order goes through `LiveTradingEngine.execute_signal`; there is
   exactly one production `exchange.create_order` call site.
6. The kill switch and live controls work from the credential alone, so a
   database outage cannot block an emergency stop.
7. Live orders and their approval rationale are audited.

Never weaken a gate to make a test pass or to “speed things up.”

## Known security gaps

- **API key role mapping:** every API-key holder maps to `admin`; use JWTs when
  distinct roles are required.
- **Approval token replay:** tokens are short-lived but not single-use. Within the
  expiry window the same token can be submitted again; `client_order_id` prevents
  a second position for the same key. A single-use store is a deferred hardening
  step.
- **JWT revocation:** no revocation list; role changes apply on next login.
  Rotating `JWT_SECRET_KEY` invalidates every outstanding approval token.
- **Metrics scope:** Prometheus counters are process-local and cumulative per
  API process; a multi-worker deployment would need multiprocess aggregation.
- **`/analyze` isolation:** runs share a process-wide gate (default one run),
  a rolling hourly budget, and a stage-start deadline that is cleared before
  execution so a committed fill is never cancelled. Results are stored per
  `session_id`; `GET /agents/status?session_id=...` reads a specific run. The
  gate/store are process-local, so a multi-worker deployment needs shared state.
  `/api/v1/metrics` remains registry-backed.

## Incident response

1. Call `/api/v1/live/kill` with a live-control credential.
2. Stop the live runner/container if the API is unreachable.
3. Do not delete logs or volumes; preserve the audit trail.
4. Rotate the API/JWT/exchange credentials if exposure is suspected.
5. Re-arm only after a human has reviewed the cause and the gates pass.

## Read next

- Full mandate: `docs/01-SPEC.md`
- Decisions: `docs/04-DECISIONS.md`
- Verified security checks: `docs/02-STATUS.md`
- Deployment: `docs/DEPLOYMENT.md`
