<!-- docs/02-STATUS.md -->
# Status — verified state

**Last verified:** 2026-10-21
**Branch:** `fix/orchestration-reliability-frontend` — 1 commit ahead / 4 behind `master` (PR #73 is already in master). The ICM restructure and P0 fixes are **uncommitted** in the working tree.
**Method:** commands run locally against the working tree, not labels copied from earlier docs.

## Green

| Check | Command | Result |
|---|---|---|
| Test suite | `pytest tests/ -q` | **1044 passed**, 2 warnings |
| Coverage | `pytest tests/ -q` | **79.08%** (gate 78%) |
| Structure | `pytest tests/test_icm_structure.py -q` | **20 passed** — contracts exist, entry file small, links resolve |
| Lint | `ruff check .` | clean |
| Format | `ruff format --check .` | clean |
| Frontend build | `pnpm build` (in `frontend/`) | passed (Next 16.2.12) |
| API ↔ frontend paths | `app.openapi()` vs `src/lib/api.ts` | every path resolves |

## P0 fixes landed (2026-10-21)

| Fix | Evidence |
|---|---|
| Auth on every non-public route | `backend/main.py` mounts every domain router with `Depends(verify_auth)`; `tests/test_security/test_route_auth.py` enumerates `/api/v1` routes and fails if one is unprotected. Default/empty `API_SECRET_KEY` returns 503; no `API_DEBUG` bypass. |
| Single-user registration, no role escalation | `/auth/register` is a one-time bootstrap that requires the operator's API key; the first account is admin and later registrations are 403. `UserRegister` has no `role` field. |
| Fail-closed, shared kill switch | `live_trading/safety.py` latches on `redis.RedisError`/`OSError`; `is_active`/`check()` return blocked; `arm()` refuses while Redis is down; after recovery a human `arm()` is required. `/live/kill` and `/live/arm` work with no exchange configured. |
| One live-order path | `agents/execution.py` calls `LiveTradingEngine.execute_signal()`; the only production `exchange.create_order` call site is `live_trading/engine.py`. Tests assert the agent never calls the exchange directly. |
| Paper-only by default | `settings.live_trading_enabled=False`; `/live/start`, `set_mode(auto\|semi)`, the agent, and the engine all refuse. Even when enabled, kill switch + mode + promotion + connection must pass. |
| Validated free roster + universal fallback | 14 unique OpenRouter free models checked against the live catalog on 2026-10-21; `defaults.universal_fallback: open_router/openrouter/free` is appended (deduplicated) by `AgentModelConfig.model_chain`. |
| Realistic paper fills and marks | `paper_trading/engine.py` applies configured commission/slippage, marks open positions with `mark_to_market`, and derives `total_pnl` from equity. The application engine wires 10 bps per side from `configs/settings.py`; direct test engines stay frictionless. |
| Correct short and fee accounting | Shorts credit proceeds, report 100% notional margin, and subtract the liability from equity. Closed trades carry entry/exit commissions; `tests/test_paper_trading.py::TestRealisticAccounting` covers fee-adjusted fills, intra-trade drawdown, and a profitable short. |
| Actual agent fill/size + promotion records | `agents/execution.py` reports/persists the engine's fill and quantity, maps long/short to `buy`/`sell` for `trade_history`, and `paper_trading/worker.py` marks each candle and inserts SL/TP closures so the promotion gate counts them. |
| Production overlay enforces secrets | `docker-compose.prod.yml` and `docker/docker-compose.prod.yml` set `ENVIRONMENT=production` for app services; the existing settings validator then refuses default API/JWT/DB secrets. Verified with `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` and `tests/test_config.py`. |
| Strict consensus threshold | `agents/consensus.py` now requires both Market Analyst and Quant confidence **strictly above** 80%, matching the spec; `tests/test_consensus.py::test_edge_confidence_exactly_80_is_rejected` locks the boundary. |

## Red / known gaps

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 1 | Two portfolio sources of truth | in-memory singleton `backend/routers/trading.py:22` vs DB projection written by `paper_trading/worker.py`; the worker now mirrors the engine on closure, but entry/reversal paths still write separately | P1 |
| 2 | `/analyze` concurrency/cost control absent | global `_last_state`, unbounded `BackgroundTasks`; auth is now required, but runs are still not isolated | P1 |
| 3 | `mypy` fails | **22 errors in 8 files**, all in `tests/` + `scripts/` (6 in `test_test_free_models.py`, 4 in `test_error_handlers.py`, 3 each in `test_analysis_router.py` and `test_paper_trading_worker.py`, 2 in `test_supervisor.py`, 2 in `scripts/test_free_models.py`, 1 each in `test_safety_edge_cases.py` and `test_engine_edge_cases.py`) | P1 (CI red) |
| 4 | Schema has three unsynchronised sources | `migrations/versions/` gitignored, two `down_revision=None` heads, `schema.sql` == `init.sql` | P1 |
| 5 | `positions` cannot represent shorts | `database/init.sql:63-83` has no side column; engine/API/trade_history carry direction, but DB position rows are unsigned | P1 |
| 6 | No role-based authorization on trading/live routes | any valid API key or JWT reaches live controls; single-user bootstrap limits exposure, but a seeded non-admin JWT is operator-level | P1 |
| 7 | UI has mock data and fake settings | `frontend/src/app/markets/page.tsx:81`, `settings/page.tsx` (no API call, 10% vs backend 2%) | P2 |
| 8 | Model catalog removals are not checked in CI | manual check only; `scripts/test_free_models.py` exists but is not a CI job | P2 |
| 9 | Kill-switch latch is process-local | a Redis outage latches each process; `/live/arm` clears the API process, but a runner that also latched stays blocked until restarted (fail-closed, never auto-trades) | P1 operational |

Full plan and acceptance criteria: `docs/05-NEXT.md`. Decisions: `docs/04-DECISIONS.md`.

## Doc accuracy

README now documents the required `API_SECRET_KEY` and dashboard login instead of quoting stale test counts.
The milestone table is historical; per-area truth lives here.
