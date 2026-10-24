<!-- docs/SETUP.md — conventional setup guide; source of commands is README and docker/ -->
# Setup — local development

> Verified commands and current service counts live in `README.md` and
> `docs/02-STATUS.md`. This guide is the short path for a new contributor.

## Prerequisites

- Docker Desktop with Compose v2+
- Python 3.11+ (CI installs 3.14; `pyproject.toml` requires `>=3.11`)
- [uv](https://docs.astral.sh/uv/) for Python environments and locked installs
- Node.js 22+ and pnpm 9.12.3 for the dashboard
- Optional: Node 22+ for the Astro landing page

## 1. Configure the environment

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the generated value in `.env` as `API_SECRET_KEY`. The shipped placeholder
is rejected with `503` on every non-public route. Also set **either**
`OPENROUTER_API_KEY` or `OPENCODE_API_KEY` for real agent reasoning; the
pipeline simulation works without them. Chat-only local use is available without
a remote key through the optional local model section below; pipeline agents
still use the remote chain.

Keep `LIVE_TRADING_ENABLED=false` and `DEFAULT_TRADING_MODE=human_approval` for
paper-only work.

## 2. Start the stack

The development stack (PostgreSQL, Redis, ChromaDB, backend, frontend,
Prometheus, Grafana):

```powershell
docker compose --env-file .env -f docker/docker-compose.yml up -d
```

The full root stack adds nginx, Postgres backups, the live runner, and the
daily reporter:

```powershell
docker compose --env-file .env up -d
```

Check health:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/health
```

`/health` returns 200 only when PostgreSQL, Redis, and ChromaDB all answer;
otherwise it returns 503 with per-check detail.

## 3. Install Python dependencies

```powershell
uv sync --locked --all-extras --dev
```

Run the pipeline wiring check (uses mock data; no API keys needed):

```powershell
uv run python scripts/simulate_pipeline.py
```

Validate configured free models (requires API keys; `--dry-run` only lists the
chains):

```powershell
uv run python scripts/test_free_models.py --dry-run
uv run python scripts/test_free_models.py
```

The free-model probe skips `local/` entries; they are opt-in and are not part of
the remote free-tier chain.

## Optional: local chat model (Strata)

The local fallback is opt-in, chat-only, and off by default. **No model is bundled
and no download starts automatically.** Start an OpenAI-compatible local server
yourself (for example Strata) before enabling it. The model ID is
`configs/models.yaml::local_chat.primary`; update that YAML entry if your server
serves a different ID, never the Python source. The shipped example is
`local/qwen3.6-35b-a3b-ud-q4_k_m`; check `/v1/models` and keep the `local/`
prefix while the server receives the bare ID. Strata's own `--parallel N` is a
server-side choice and is separate from the application's process-wide gate.

For a host-run backend, point at loopback:

```dotenv
LOCAL_LLM_ENABLED=true
LOCAL_LLM_BASE_URL=http://127.0.0.1:8080/v1
```

For the Compose backend, `127.0.0.1` is the container itself. The dev Compose
stack already publishes the backend on host **8080**, so run Strata on another
host port and use Docker Desktop's host alias. The shipped `.env.example` uses
8081:

```dotenv
LOCAL_LLM_ENABLED=true
LOCAL_LLM_BASE_URL=http://host.docker.internal:8081/v1
```

Use any free host port for Strata; only `LOCAL_LLM_BASE_URL` must match it.

No API key is sent. The defaults are a 90 s model timeout, one concurrent local
request process-wide, and a 20 s queue wait; a busy local model returns **503**
instead of retrying or tripping its circuit breaker. Restart the backend after
changing these values. With a remote provider
configured, local is used only after the remote `chat` chain is exhausted. With
no remote key, chat is local-only. Local routing is not enabled for pipeline
agents. Check the server directly before opening the dashboard:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/v1/models
```

## 4. Run the dashboard

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://localhost:3000`. The login screen asks for `API_SECRET_KEY`; it is
stored in `sessionStorage` for the tab and sent as `X-API-Key`. A new tab asks
again.

Landing page:

```powershell
cd landing
npm install
npm run dev
```

Open `http://localhost:4321`.

## 5. Run the checks

```powershell
# Narrow first
python -m pytest tests/test_icm_structure.py -q --no-cov
python -m pytest tests/ -q

ruff check .
ruff format --check .
mypy .
```

Frontend build:

```powershell
cd frontend
pnpm build
```

## Ports and service names

| Service | Local port |
|---|---|
| FastAPI | 8000 |
| Next.js dashboard | 3000 |
| Astro landing | 4321 |
| PostgreSQL | 5432 |
| Redis | 6379 |
| ChromaDB | 8000 inside Compose; 8001 published in dev |
| Prometheus | 9090 |
| Grafana | 3001 |
| nginx (root stack) | 8080 |

Inside Compose, use service hostnames (`postgres`, `redis`, `chromadb`), not
`localhost`. The Compose files force internal hostnames so a host-oriented
`.env` does not break containers.

## Common first-run problems

- **Every API call returns 503** — `API_SECRET_KEY` is empty or still the
  default. Generate a unique value and restart the backend.
- **401 on the dashboard** — the key entered at `/login` is wrong; clear the
  tab's `sessionStorage` and log in again.
- **ChromaDB unhealthy / client version error** — the Compose stack pins
  ChromaDB `1.5.9` and mounts `/data`; do not use the old `/chroma/chroma`
  path.
- **Alembic multiple heads** — run `python -m alembic heads`; there must be one
  head. Fix the branch, do not stamp over it.
- **PostgreSQL integration tests skip locally** — set
  `ARES_TEST_POSTGRES_URL` and `ARES_REQUIRE_POSTGRES_INTEGRATION=1`.

## Read next

- Deployment and production overlay: `docs/DEPLOYMENT.md`
- API routes: `docs/API.md`
- Auth and secrets: `docs/AUTH_SECURITY.md`
- Debugging: `docs/DEBUGGING.md`
