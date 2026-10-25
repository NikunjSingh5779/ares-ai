# Changelog

All notable changes to ARES AI are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project version from `pyproject.toml`. Canonical verified state, measured
counts, and known gaps live in `docs/02-STATUS.md`; milestone history lives in
`docs/milestone-roadmap.md`.

## [Unreleased]

### Added

- Conventional documentation set: `docs/PRD.md`, `docs/DATABASE.md`,
  `docs/API.md`, `docs/IMPLEMENTATION.md`, `docs/SETUP.md`, `docs/FEATURES.md`,
  `docs/DEPLOYMENT.md`, `docs/AUTH_SECURITY.md`, `docs/MCP.md`,
  `docs/INTEGRATIONS.md`, `docs/TESTING.md`, `docs/DEBUGGING.md`,
  `docs/TASKS.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md`, and
  `docs/CONVENTIONS.md`.
- `LICENSE` with a proprietary, all-rights-reserved notice.
- `CHANGELOG.md`.

### Changed

- `README.md` now points at the conventional docs and no longer quotes a
  stale coverage number; verified counts remain in `docs/02-STATUS.md`.
- `CLAUDE.md` is now exactly `@AGENTS.md` instead of a second copy.
- `docs/00-INDEX.md` lists the conventional reference docs.
- `docs/architecture.md` (the historical M1 target) is now a pointer to the
  canonical `docs/03-ARCHITECTURE.md`.
- `.mcp.json` uses the PostgreSQL connection-string argument expected by the
  reference MCP server.
- `.gitignore` covers Node/Next/Astro build output and local database files.

### Security

- No safety gate changed. Live trading remains disabled by default
  (`LIVE_TRADING_ENABLED=false`) and every live order still passes the
  kill switch, mode, promotion, and exchange gates.

## [0.1.0] — 2026-10-22

### Added

- Phase 0 capital-safety work: auth on every non-public route, one fail-closed
  live-order path, universal model fallback, realistic paper accounting, and
  production configuration enforcement.
- P1-A: durable PostgreSQL paper ledger with hydration, atomic writes, and
  restart safety (`9c16122`).
- P1-B: approved-only `/execute` with mandatory `client_order_id` and
  `409` duplicate rejection.
- P1-C: transaction-scoped advisory lock plus in-process cache lock for paper
  writers (`2bf10d0`).
- P1.4: real-PostgreSQL integration job in GitHub Actions (`b6b5bea`).
- P1.5: `/health` returns `503` when PostgreSQL, Redis, or ChromaDB is
  degraded; `/api/v1/metrics` is Prometheus-backed.
- P1.6: role-based authorization (`viewer`, `operator`, `admin`,
  `super_admin`) with JWT role claims and API-key mapping.
- Phase 1 Compose exit: two concurrent paper fills survived a full-stack
  restart with portfolio, positions, orders, and promotion record unchanged.

### Changed

- Compose bootstrap now applies `init.sql`, stamps Alembic `0001`, then runs
  migrations `0002`–`0004`; ChromaDB is pinned to `1.5.9` and persisted at
  `/data`.

### Fixed

- Windows checkout CRLF entrypoint failure (`.gitattributes` forces LF for
  shell scripts).
- Container-to-container service hostnames no longer inherit host-oriented
  `.env` values.
- Stale `_last_state` reads in the JSON metrics endpoint.
- Mypy errors in tests and scripts (184 source files clean).

### Security

- Default or empty `API_SECRET_KEY` is rejected with `503` on every non-public
  route; production refuses default JWT and database passwords.
- The kill switch latches closed and requires human re-arm.
- Live order placement has exactly one production call site
  (`live_trading/engine.py`).
