<!-- docker/CONTEXT.md -->
# docker/ — contract

**Purpose:** build images, run the stack, expose it safely, observe it, back it up.

## Layout
- Root `docker-compose.yml` — dev stack (postgres, redis, chroma, backend, worker, frontend, nginx, prometheus, grafana, backup).
- `docker/docker-compose.yml` — full-stack variant; `docker-compose.dev.yml` — dev overlay.
- `Dockerfile` (backend), `frontend/Dockerfile`, `docker/nginx/`, `docker/backup/`.
- `docker/monitoring/` — the single tracked monitoring set: Prometheus scrape
  config, `alert-rules.yml`, Grafana datasource/dashboard provisioning, and two
  dashboards. Both compose files mount these files.
- `.github/workflows/ci.yml` — lint, tests, real-PostgreSQL integration, compose validation, image builds.
- `.github/workflows/model-catalog.yml` — weekly live model-catalog probe (requires the `OPENROUTER_API_KEY` secret).

## Invariants
- Production compose sets `ENVIRONMENT=production` and real secrets (currently missing).
- No secret is baked into an image; compose reads `.env`.
- Healthchecks test readiness, not just an open port. The backend healthcheck now fails on
  the 503 that `/health` returns when PostgreSQL, Redis, or ChromaDB is unreachable.
- Shell entrypoints stay LF (`.gitattributes`); a CRLF `backend-entrypoint.sh` fails Docker
  with `exec /entrypoint.sh: no such file or directory`.
- `docker/docker-compose.yml` forces container-internal `postgres`/`redis`/`chromadb` hosts.
  The root `.env` is host-oriented and must not be interpolated into the backend container.
- On a fresh volume `init.sql` creates the schema; the entrypoint detects the missing
  Alembic version row and stamps `0001` before applying `0002`–`0006`.
- The Chroma server image is pinned to **1.5.9** to match the Python client. The 1.x image
  writes to **`/data`**; mount `chromadb-data` there, not at the 0.5.0 path
  `/chroma/chroma-data`. The 1.x image has no curl/python, so its container healthcheck is
  disabled; the backend waits for `service_started` and `/health` reports Chroma until it
  answers.
- Images are reproducible: pin the Python version and use the lockfile.
- One tracked monitoring set in `docker/monitoring/`; both compose files mount it.
  Prometheus evaluates `alert-rules.yml` (7 rules). The dev stack has no
  Alertmanager, so rules appear on `/alerts` and in `ALERTS` but are not delivered
  anywhere.

## Human check
`docker compose config --quiet`, `docker compose up -d`, `curl localhost:8080/health`,
Grafana dashboard loads, `docker/backup/backup.sh` produces an archive. The full-stack
override command from the repo root is
`docker compose --env-file .env -f docker/docker-compose.yml up -d`; never print resolved
Compose output because it contains `.env` secrets.

## Tests
`tests/test_infra_config.py`; CI validates compose.

## Known gaps
No `ENVIRONMENT=production`; backend Python 3.11 + unpinned `pip install .` vs CI 3.14 +
`uv --locked`; no Alertmanager target, so alert rules are visible but not paged. The local
`.env` `API_SECRET_KEY` is still a default placeholder, so `/api/v1/*` returns 503 until a
real key is set.
