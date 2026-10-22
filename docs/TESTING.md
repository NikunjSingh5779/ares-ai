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
- Agent, router, ledger, role, monitoring, schema, and worker tests are separate
  modules; run the narrowest one first.

## Commands

```powershell
# Structure only (fast)
python -m pytest tests/test_icm_structure.py -q --no-cov

# One area
python -m pytest tests/test_paper_trading_ledger.py -q
python -m pytest tests/test_trading_router.py -q
python -m pytest tests/test_security/test_role_auth.py -q

# Full suite with the configured coverage gate (78%)
python -m pytest tests/ -q
```

The default `addopts` in `pyproject.toml` enables coverage over `backend`,
`agents`, `database`, `backtesting`, `paper_trading`, and `live_trading`, and
fails under 78%. The last verified run was **1196 passed, 1 skipped, 81.11%**
(2026-10-22). Do not copy that number into a new claim without re-running.

## Real PostgreSQL tests

```powershell
$env:ARES_TEST_POSTGRES_URL = "postgresql+asyncpg://ares:ares_test@localhost:5432/ares_ai_test"
$env:ARES_REQUIRE_POSTGRES_INTEGRATION = "1"
python -m pytest tests/test_postgres_integration.py -q --no-cov
```

The CI `postgres-integration` job starts `postgres:16-alpine`, loads
`database/schema.sql`, and runs the module. With
`ARES_REQUIRE_POSTGRES_INTEGRATION=1`, a missing URL is a hard failure, not a
silent skip.

## Lint, format, types

```powershell
ruff check .
ruff format --check .
mypy .
```

The CI `lint` job installs Python 3.14 with `uv` and runs all three. Mypy is
clean on 198 source files as of 2026-10-22. New code must not add
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
(`src/**/*.test.ts[x]`); `vitest.setup.ts` installs jest-dom matchers and clears
sessionStorage between tests. The current suite is **14 tests** in 3 files:
`src/lib/api.test.ts` (error detail, timeout, abort, API-key header, 401),
`src/lib/usePipelinePolling.test.tsx` (start-after-accept, backoff, single-flight,
60 s timeout), and `src/components/AuthGate.test.tsx` (redirect and main landmark).
`react-hooks/set-state-in-effect` is disabled in `eslint.config.mjs` for the existing
fetch-on-mount pages; the remaining React Compiler rules stay on.

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
