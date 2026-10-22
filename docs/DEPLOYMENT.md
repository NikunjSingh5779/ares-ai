<!-- docs/DEPLOYMENT.md — conventional deployment guide; CI validates, deployment is manual -->
# Deployment — ARES AI

> There is no automated deployment workflow. GitHub Actions validates the code;
> a human deploys. Live trading remains disabled unless every safety gate is
> explicitly satisfied.

## Deployment options

| Stack | Command | Services |
|---|---|---|
| Development / core | `docker compose --env-file .env -f docker/docker-compose.yml up -d` | postgres, redis, chromadb, backend, frontend, prometheus, grafana |
| Full root stack | `docker compose --env-file .env up -d` | core seven plus nginx, backup, run-live, daily-reporter (11) |
| Production overlay (root) | `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` | Full stack with production config enforcement |
| Production overlay (docker/) | `docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d` | Core stack with production config enforcement |

The production overlays set `ENVIRONMENT=production`. Startup fails unless
`API_SECRET_KEY`, `JWT_SECRET_KEY`, and the PostgreSQL password are all
non-default. The overlay does **not** enable live trading; the kill switch,
mode, promotion, and exchange gates still apply.

## Pre-deployment checklist

1. `.env` exists and is not committed; `.env.example` is the template.
2. `API_SECRET_KEY` is unique and non-default.
3. `JWT_SECRET_KEY` is unique and non-default.
4. `POSTGRES_PASSWORD` is unique and matches `DATABASE_URL`.
5. `OPENROUTER_API_KEY` or `OPENCODE_API_KEY` is set if agent reasoning is
   required.
6. `LIVE_TRADING_ENABLED=false` unless a human has completed every live gate.
7. `DEFAULT_TRADING_MODE=human_approval` for the default deployment.
8. TLS terminates at nginx or another trusted proxy; `TRUSTED_PROXIES` is set
   only when a proxy supplies `X-Forwarded-For`.
9. `API_CORS_ORIGINS` lists only the real dashboard origin(s).
10. Backups are configured and tested; the root stack includes a backup
    service but restore is an operator responsibility.

## Bring-up sequence

```powershell
# 1. Validate interpolation and config
docker compose --env-file .env -f docker/docker-compose.yml config

# 2. Start
docker compose --env-file .env -f docker/docker-compose.yml up -d

# 3. Wait for health
Invoke-WebRequest -UseBasicParsing http://localhost:8000/health

# 4. Confirm auth and metrics
Invoke-WebRequest -UseBasicParsing `
  -Headers @{ "X-API-Key" = $env:API_SECRET_KEY } `
  http://localhost:8000/api/v1/metrics
```

Do not print `.env` or the API key into logs, screenshots, issue reports, or
chat. Use a secret manager or the deployment platform's environment injection
for production.

## Database and migrations

- `database/init.sql` runs only on a fresh PostgreSQL volume.
- The backend entrypoint stamps Alembic `0001` when `init.sql` created the
  schema, then applies the idempotent `0002`–`0005` revisions.
- For an existing database, run `python -m alembic upgrade head` before
  starting the new backend.
- `python -m alembic heads` must show exactly one head.
- Back up before a migration; never edit an applied migration in place.

## Persistence

| Data | Volume / mount |
|---|---|
| PostgreSQL | `postgres-data` (or `postgres_data` in the root stack) |
| Redis | `redis-data` |
| ChromaDB | `chromadb-data`, mounted at `/data` with ChromaDB `1.5.9` |
| Prometheus / Grafana | `prometheus-data`, `grafana-data` |
| Backups (root stack) | `backup_data` |

ChromaDB 1.x uses `/data`; the older `/chroma/chroma` path is wrong for this
stack. Do not change the image tag without checking the Python client version.

## Health, monitoring, and rollback

- `/health` returns 200 only when PostgreSQL, Redis, and ChromaDB answer; 503
  includes per-check detail. Compose healthchecks consume the status code.
- `/metrics` is the Prometheus scrape target. `/api/v1/metrics` is the
  authenticated JSON summary.
- Logs: `docker compose logs -f backend`, `frontend`, `postgres`, `redis`,
  `chromadb`.
- Rollback: redeploy the previous image/commit and restore the database from a
  tested backup. Do not run destructive volume commands without explicit
  approval.
- The root stack includes nginx and a backup service; verify the backup and
  restore path before relying on it.

## Live-trading deployment gate

Live trading is a separate, explicit decision:

1. Paper-trading promotion record meets the configured threshold.
2. Kill switch is armed and healthy.
3. `LIVE_TRADING_ENABLED=true` is set intentionally.
4. Human-approval mode is the default for every new strategy/account.
5. Exchange credentials are scoped to trading only and never committed.
6. A human re-arms after any kill.

Never deploy with an empty API key, default JWT secret, default database
password, or an unreviewed bypass of the kill switch.

## Read next

- Setup: `docs/SETUP.md`
- Auth and secrets: `docs/AUTH_SECURITY.md`
- Integrations: `docs/INTEGRATIONS.md`
- CI workflow: `.github/workflows/ci.yml`
