<!-- docker/CONTEXT.md -->
# docker/ — contract

**Purpose:** build images, run the stack, expose it safely, observe it, back it up.

## Layout
- Root `docker-compose.yml` — dev stack (postgres, redis, chroma, backend, worker, frontend, nginx, prometheus, grafana, backup).
- `docker/docker-compose.yml` — full-stack variant; `docker-compose.dev.yml` — dev overlay.
- `Dockerfile` (backend), `frontend/Dockerfile`, `docker/nginx/`, `docker/backup/`.
- `docker/prometheus/` + `docker/grafana/` **and** `docker/monitoring/` — duplicate monitoring sets.
- `.github/workflows/ci.yml` — lint, tests, real-PostgreSQL integration, compose validation, image builds.

## Invariants
- Production compose sets `ENVIRONMENT=production` and real secrets (currently missing).
- No secret is baked into an image; compose reads `.env`.
- Healthchecks test readiness, not just an open port.
- Images are reproducible: pin the Python version and use the lockfile.
- One monitoring config set; delete the duplicate when consolidating.

## Human check
`docker compose config`, `docker compose up -d`, `curl localhost:8000/health`,
Grafana dashboard loads, `docker/backup/backup.sh` produces an archive.

## Tests
`tests/test_infra_config.py`; CI validates compose.

## Known gaps
Healthcheck always passes while `/health` says degraded; no `ENVIRONMENT=production`;
backend Python 3.11 + unpinned `pip install .` vs CI 3.14 + `uv --locked`; duplicate
monitoring configs; no Prometheus alert rules.
