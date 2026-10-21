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
- `conftest.py` — shared fixtures; overrides `verify_auth` for domain tests only.
  Auth-specific tests remove the override and exercise the real gate.

## Rules
- Deterministic: fake LLMs/HTTP, no real keys, no sleeps for timing.
- Each test owns its state; no dependency on test order.
- A regression test accompanies every safety/correctness fix.
- Coverage gate is 78% (`pyproject.toml`); do not lower it to pass.

## Running
- Narrow: `pytest tests/test_<area>/test_<module>.py -q`
- Full: `pytest tests/ -q`
- Types: `mypy .` (currently red on tests/scripts — see `docs/02-STATUS.md`)

## Human check
Full suite green, `ruff check .`, `mypy .`, and no new warnings.

## Known gaps
No full-pipeline e2e with a fake LLM. The route-auth test enumerates `/api/v1`;
`/users/*` and `/auth/verify` are covered by per-route dependencies. PostgreSQL
integration (including duplicate `client_order_id` races) is still a manual check, not a
CI job.
