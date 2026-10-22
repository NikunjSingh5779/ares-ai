<!-- docs/DEBUGGING.md — common failures and safe diagnostics -->
# Debugging — ARES AI

> Diagnose with read-only commands first. Never print `.env`, API keys, JWTs, or
> exchange secrets. Never disable a safety gate to “see if it works.”

## First checks

```powershell
git status --short
Invoke-WebRequest -UseBasicParsing http://localhost:8000/health
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs --tail=100 backend
```

- `/health` 200 means PostgreSQL, Redis, and ChromaDB all answered.
- `/health` 503 includes per-check JSON; fix the failing dependency first.
- Authenticated routes need `X-API-Key`; a missing key is 401, a default key is
  503.

## API returns 503 everywhere

**Cause:** `API_SECRET_KEY` is empty or still `changeme_in_production`.

**Fix:** generate a unique key and restart the backend:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Put the value in .env as API_SECRET_KEY; never commit it.
docker compose -f docker/docker-compose.yml up -d backend
```

## API returns 401

- The dashboard key entered at `/login` is wrong.
- The `X-API-Key` header is missing or the Bearer token is malformed.
- Clear the tab's `sessionStorage` and log in again.

## API returns 403 on `/execute` or live controls

The JWT role is `viewer` or missing. Log in with an operator/admin role, or use
the API key (maps to `admin`). Role changes apply on the next login; there is no
revocation list.

## PostgreSQL connection errors

- Inside Compose, the host is `postgres`, not `localhost`.
- The host `.env` may point at `localhost`; the Compose files force internal
  service hostnames for containers.
- Check `docker compose ... ps postgres` and
  `docker compose ... logs postgres`.
- Verify `DATABASE_URL` uses `postgresql+asyncpg://` for the Python app and
  `postgresql://` for the MCP Postgres server.

## Alembic problems

```powershell
python -m alembic current
python -m alembic heads
python -m alembic upgrade head
```

- More than one head is a branch bug; merge the revisions, do not stamp over
  them.
- A fresh Compose volume runs `init.sql`, stamps `0001`, then applies
  `0002`–`0005`. If the stamp is wrong, inspect the entrypoint logs.
- Never edit an applied migration; create a new revision.

## Paper trading errors

| Symptom | Meaning | Action |
|---|---|---|
| `409` | Duplicate `client_order_id` | Reuse the original request ID or generate a new one |
| `503` with `Retry-After: 1` | Writer lock busy | Retry after the lock window; do not bypass the ledger |
| `422` | Missing/invalid approvals or schema | Inspect the request and `/docs`; do not invent approvals |
| `503` on `/portfolio` | Ledger unavailable | Check PostgreSQL and the backend logs |

The in-memory engine is a cache. If PostgreSQL is down, do not “fix” it by
writing to memory only; the request must fail closed.

## ChromaDB / memory errors

- Compose pins ChromaDB `1.5.9` to match the Python client.
- The volume must mount at `/data` for ChromaDB 1.x; `/chroma/chroma` is wrong.
- ChromaDB has no container healthcheck (the image lacks curl/python);
  `/health` is the readiness signal.
- A missing collection or empty memory is not a crash; check the memory agent
  logs and the `memories` table.

## Redis / kill switch

- A Redis outage must reject live execution; recovery still requires human
  re-arm.
- Do not clear the kill-switch key manually in production. Use `/live/arm` with
  a live-control credential after review.
- The arm epoch is process-local; a multi-runner deployment needs the shared
  epoch work in `docs/05-NEXT.md`.

## Frontend problems

- `NEXT_PUBLIC_API_URL` must point to the backend (default
  `http://localhost:8000`, not `8080`).
- A CORS error means `API_CORS_ORIGINS` does not include the dashboard origin.
- A blank page or redirect loop usually means no key in `sessionStorage`;
  `AuthGate` sends you to `/login`.
- `pnpm build` is the supported check. `pnpm lint` is invalid under Next 16
  until the Phase 2 CI work lands.
- Markets, settings, and strategy-builder now read/write the backend; there is no
  mock-data fallback. If they show defaults or an empty list, check auth and
  `NEXT_PUBLIC_API_URL` connectivity rather than looking for seeded UI values.
- The chat page triggers `POST /api/v1/analyze`; it does not yet maintain a
  multi-turn agent conversation.

## CI failures

```powershell
gh run list --limit 5
gh run view <run-id> --log-failed
```

- `lint` — Ruff/format/mypy; run the narrow command locally first.
- `test` — full pytest; check for a missing PostgreSQL/Redis service.
- `postgres-integration` — real DB; confirm `ARES_REQUIRE_POSTGRES_INTEGRATION=1`.
- `frontend` — pnpm build; check Node/pnpm versions.
- `docker` — Compose interpolation/build; check `.env.example` and service
  names.

## Logs and metrics

- `docker compose logs -f backend` — API, auth, ledger, live safety.
- `agent_logs` — model, error type, latency, fallback used.
- `/metrics` — Prometheus exposition.
- `/api/v1/metrics` — authenticated JSON counters.
- Do not paste raw logs containing secrets into an issue or chat.

## Read next

- Testing: `docs/TESTING.md`
- Setup: `docs/SETUP.md`
- Deployment: `docs/DEPLOYMENT.md`
- Verified state: `docs/02-STATUS.md`
