<!-- docs/TESTING.md — conventional testing guide; verified counts live in 02-STATUS.md -->
# Testing — ARES AI

> `docs/02-STATUS.md` is the source of truth for the last verified count and
> coverage. This guide explains how to run and extend the checks.

## Test layout

- `tests/` mirrors module paths: `tests/test_<area>/test_<module>.py`.
- `tests/test_icm_structure.py` enforces folder contracts, the root entry
  catalog budget, and relative links in entry documents.
- `tests/test_postgres_integration.py` exercises the durable paper ledger
  against a real PostgreSQL 16 instance and is skipped unless a URL is set.
- `tests/test_postgres_strategy_integration.py` exercises the strategy draft
  routes and JSONB persistence against the same opt-in disposable database.
- `tests/test_postgres_improvement_integration.py` exercises the reflection run →
  improvement record → API round-trip against the same database.
- Agent, router, ledger, role, monitoring, schema, and worker tests are separate
  modules; run the narrowest one first.

## Commands

```powershell
# Structure only (fast)
python -m pytest tests/test_icm_structure.py -q --no-cov

# One area
python -m pytest tests/test_paper_trading_ledger.py -q
python -m pytest tests/test_trading_router.py -q
python -m pytest tests/test_chat_router.py tests/test_chat_service.py -q
python -m pytest tests/test_improvement.py tests/test_improvement_service.py tests/test_agents_router.py -q
python -m pytest tests/test_infra_config.py -q
python -m pytest tests/test_local_gate.py tests/test_client.py tests/test_router.py -q
python -m pytest tests/test_security/test_role_auth.py -q

# Full suite with the configured coverage gate (78%)
python -m pytest tests/ -q
```

The default `addopts` in `pyproject.toml` enables coverage over `backend`,
`agents`, `database`, `backtesting`, `paper_trading`, and `live_trading`, and
fails under 78%. The last verified run was **1259 passed, 3 skipped, 82.17%**
(2026-10-24). Do not copy that number into a new claim without re-running.

## Real PostgreSQL tests

```powershell
$env:ARES_TEST_POSTGRES_URL = "postgresql+asyncpg://ares:ares_test@localhost:5432/ares_ai_test"
$env:ARES_REQUIRE_POSTGRES_INTEGRATION = "1"
python -m pytest tests/test_postgres_integration.py tests/test_postgres_strategy_integration.py tests/test_postgres_improvement_integration.py -q --no-cov
```

The CI `postgres-integration` job starts `postgres:16-alpine`, loads
`database/schema.sql`, and runs all three modules. With
`ARES_REQUIRE_POSTGRES_INTEGRATION=1`, a missing URL is a hard failure, not a
silent skip. Every module refuses to run unless the target database name
contains `test`; the strategy fixture deletes only `strategies` rows, and the
improvement fixture deletes only `improvement_records` then `reflection_runs`.
On a disposable PostgreSQL 16 container the combined run was **23 passed**
(5 ledger, 12 strategy, and 6 improvement).

## Local model tests

The `local/` provider tests use `pytest-httpx` and a fake async gate; they do not
start Strata or require a GPU. They cover prefix stripping, no `Authorization`
header, `reasoning_effort="off"`, gate serialization/timeout, local-only chain
selection, and the local-plus-remote fallback chain. A live local smoke test is
manual and opt-in through `LOCAL_LLM_ENABLED=true`. On 2026-10-24 Strata served
`qwen3.6-35b-a3b-ud-q4_k_m`: a direct client reply took **0.49 s**, the local-only
`ChatService` reply took **0.99 s**, and `POST /api/v1/chat` returned **200**.

## Lint, format, types

```powershell
ruff check .
ruff format --check .
mypy .
```

The CI `lint` job installs Python 3.14 with `uv` and runs all three. Mypy is
clean on 211 source files as of 2026-10-24. New code must not add
`# type: ignore` to hide a real mismatch.

## Frontend

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm lint        # eslint . --max-warnings=0
pnpm typecheck   # tsc --noEmit
pnpm test        # vitest run (jsdom + Testing Library)
pnpm build       # next build
```

The CI `frontend` job runs all four in that order. Tests live beside the code
(`src/**/*.test.ts[x]`); `vitest.setup.ts` installs jest-dom matchers, clears
sessionStorage between tests, and stubs `scrollIntoView` for the chat log. The
current suite is **18 tests** in 4 files:
`src/lib/api.test.ts` (error detail, timeout, abort, API-key header, 401),
`src/lib/usePipelinePolling.test.tsx` (start-after-accept, backoff, single-flight,
60 s timeout), `src/components/AuthGate.test.tsx` (redirect and main landmark),
and `src/app/chat/page.test.tsx` (empty state, prior-turn history, retry, clear).
`react-hooks/set-state-in-effect` is disabled in `eslint.config.mjs` for the existing
fetch-on-mount pages; the remaining React Compiler rules stay on.

## Accessibility

The manual pass uses a production build served locally. Lighthouse 13.5.0 audits
`/login` with `--only-categories=accessibility`; axe-core 4.14.0 runs over the
authenticated routes through Chrome DevTools Protocol with a dummy tab-scoped key
and `/api/v1/*` stubbed to **503** so no real credential is used. On 2026-10-24
Lighthouse scored **100** and axe reported **0 violations across 16 routes**. The
stub means data-populated tables, charts, and dialogs are not exercised; re-run
with a real session before claiming those states.

## Docker / Compose

```powershell
docker compose -f docker/docker-compose.yml config
docker compose -f docker/docker-compose.yml build
```

The CI `docker` job copies `.env.example` to `.env`, validates
`docker-compose.yml`, and builds the images. It does not start the full stack.

## What to test for each change

| Change | Minimum test |
|---|---|
| Agent behavior or schema | Agent output schema, fallback, rejection path |
| API route | Auth, role denial, validation, error codes |
| Paper ledger / fill | Hydration, atomic write, duplicate, lock timeout, restart |
| Live safety gate | Kill switch, mode, promotion, exchange failure |
| DB schema | `tests/test_schema.py`, migration chain, integration test |
| Frontend page | Build, auth redirect, loading/empty/error states, no mock data |
| Docs structure | `tests/test_icm_structure.py` |

## Test rules

- A required agent failure must reject a trade; never assert an approval.
- Never weaken a safety gate, timeout, or assertion to make a test pass.
- Mock external networks; do not call live exchanges or model providers in
  tests.
- Do not commit secrets, API keys, or generated `.env` files.
- Add a regression test with every bug fix.
- Update `docs/02-STATUS.md` only with measured results.

## Read next

- CI workflow: `.github/workflows/ci.yml`
- Debugging failures: `docs/DEBUGGING.md`
- Test contract: `tests/CONTEXT.md`
