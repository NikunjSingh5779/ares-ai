<!-- tests/CONTEXT.md -->
# tests/ — contract

**Purpose:** prove behaviour without live models, exchanges, or production data.

## Layout
- `test_agents/` — agent edge cases, routing, news, candlesticks.
- `test_backend/` — router/service tests.
- `test_live_trading/` — engine, safety, routes, audit, exchange adapters.
- `test_monitoring/` — metrics, health, middleware.
- `test_security/` — auth, rate limiting, headers, crypto, error handlers.
- Root `test_*.py` — one file per module (supervisor, consensus, risk, paper, backtest…).
- `test_settings_router.py` / `test_settings_service.py` — read-only safety block,
  preference validation/normalization, 422 on override attempts, 503 on store failure,
  and durable merge/upsert behavior.
- `test_postgres_integration.py` — opt-in real-PostgreSQL ledger tests; skipped unless
  `ARES_TEST_POSTGRES_URL` points at a disposable database whose name contains `test`.
- `test_postgres_strategy_integration.py` — opt-in strategy route/service/JSONB tests
  with the same guard; deletes only `strategies` rows.
- `test_postgres_improvement_integration.py` — opt-in reflection/improvement
  route/service/JSONB tests with the same guard; deletes only `improvement_records`
  then `reflection_runs`.
- `conftest.py` — shared fixtures; overrides `verify_auth` **and** the role dependencies
  (`require_trading_access`, `require_live_control`) for domain tests only. Auth/role
  tests remove those overrides and exercise the real gates.

## Rules
- Deterministic: fake LLMs/HTTP, no real keys, no sleeps for timing.
- Each test owns its state; no dependency on test order.
- A regression test accompanies every safety/correctness fix.
- Coverage gate is 78% (`pyproject.toml`); do not lower it to pass.
- Never point `ARES_TEST_POSTGRES_URL` at a real ledger. The ledger module truncates
  `users`/`accounts` and the paper tables; the strategy and improvement fixtures delete
  only their own tables. All modules refuse non-test database names.

## Running
- Narrow: `pytest tests/test_<area>/test_<module>.py -q`
- Full: `pytest tests/ -q`
- Real PostgreSQL: `ARES_TEST_POSTGRES_URL=postgresql+asyncpg://ares:ares_test@localhost:5432/ares_ai_test pytest tests/test_postgres_integration.py tests/test_postgres_strategy_integration.py tests/test_postgres_improvement_integration.py -q --no-cov`
  (CI job `postgres-integration` does this on `postgres:16-alpine`).
- Types: `mypy .` (clean on 211 files as of 2026-10-24)

## Human check
Full suite green, `ruff check .`, `mypy .`, and no new warnings.

## Known gaps
No full-pipeline e2e with a fake LLM. The route-auth test enumerates `/api/v1`;
`/users/*` and `/auth/verify` are covered by per-route dependencies. The integration job
covers the ledger SQL, duplicate IDs, concurrent writers, the advisory lock, strategy
drafts, and improvement history; it does not yet restart a Compose stack (Phase 1 exit).
