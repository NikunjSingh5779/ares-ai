<!-- docs/04-DECISIONS.md -->
# Decisions (ADR log)

One entry per structural decision. Newest last. A decision is not a task: tasks live
in `05-NEXT.md`, state lives in `02-STATUS.md`.

---

## ADR-001 — Adopt ICM for navigation and MVC for code placement
**Date:** 2026-10-20 · **Status:** accepted

**Context:** A read-only audit found that the code works but the repository does not
explain itself: no per-folder contract, a 192-line entry file, stale architecture
docs, and no map from a symptom to the file that owns it.

**Decision:** Use ICM for the root/docs layer and MVC naming for code responsibilities.
ICM files contain no code; code files contain no project rationale.

**Consequences:** `AGENTS.md` becomes a catalog; each folder gets `CONTEXT.md`;
`docs/map/` answers "what else moves if I change X". A test enforces link integrity.

---

## ADR-002 — Do not move code during this restructure
**Date:** 2026-10-20 · **Status:** accepted

**Context:** `icm-mvc-structure` says existing projects should map the real layout,
not reorganise it. The suite is 988 tests and the branch is 4 commits behind master.

**Decision:** Map existing paths to MVC roles (`docs/03-ARCHITECTURE.md` §3). Do not
rename `backend/routers/` to `controllers/` or move schemas as part of this change.

**Consequences:** Zero import churn, zero behaviour change. A future, separately
approved change may rename modules; it must land with tests and updated links.

---

## ADR-003 — The root entry file routes; the mandate lives on a shelf
**Date:** 2026-10-20 · **Status:** accepted

**Decision:** `AGENTS.md` is a ~70-line catalog with a 10-rule non-negotiable block.
The full 192-line mandate moves verbatim to `docs/01-SPEC.md`.

**Consequences:** One home per fact. Any future rule change edits `01-SPEC.md`; only
a change to the non-negotiables edits `AGENTS.md`. `CLAUDE.md` keeps pointing here.

---

## ADR-004 — Status is a verified file, not a label
**Date:** 2026-10-20 · **Status:** accepted

**Decision:** `docs/02-STATUS.md` holds only commands that were run and their results,
with a date. Roadmap rows are historical; they do not override status.

**Consequences:** Updating status requires re-running the check, not editing a badge.

---

## ADR-005 — One portfolio source of truth (accepted, implementation pending)
**Date:** 2026-10-20 · **Status:** accepted, **not implemented**

**Context:** The API keeps an in-memory `PaperTradingEngine` while the runner and DB
hold separate state. A restart silently resets capital to $100k.

**Decision:** Persist portfolio/positions/trades in PostgreSQL and make every process
read/write through one repository. The in-memory engine may remain a cache only.

**Consequences:** Phase 1 work. Until it lands, `02-STATUS.md` records the dual source
and no feature may add a third.

---

## ADR-006 — Every live order goes through one gate
**Date:** 2026-10-20 · **Status:** **implemented** (2026-10-21)

**Context:** `agents/execution.py` could call `exchange.create_order` directly, skipping
the kill switch, mode check, and audit log.

**Decision:** `LiveTradingEngine.execute_signal()` is the only path to an exchange.
The order path evaluates a fail-closed kill switch shared across processes.

**Consequences:** `ExecutionAgent` calls `execute_signal`; the engine checks the kill
switch, mode, promotion gate, and connection, then records the order. The only
production `exchange.create_order` call site is `live_trading/engine.py`. New live
connectors or signals must not add another order call site.

---

## ADR-007 — The model roster has a universal fallback
**Date:** 2026-10-20 · **Status:** **implemented at runtime** (2026-10-21); CI catalog check still pending

**Decision:** `configs/models.yaml` contains only validated free IDs and declares
`defaults.universal_fallback: open_router/openrouter/free`. `AgentModelConfig`
appends that model after every explicit fallback (deduplicated). A catalog check
(`scripts/test_free_models.py`) remains the manual validation tool.

**Consequences:** A dead chain still reaches one validated free model. The roster was
checked against the live OpenRouter catalog on 2026-10-21 (14 unique free models,
all present). A CI job that detects future catalog removals remains Phase 3 work.

---

## ADR-008 — Structure is enforced by a test, not by convention
**Date:** 2026-10-20 · **Status:** accepted

**Decision:** `tests/test_icm_structure.py` fails if a working folder lacks
`CONTEXT.md`, if `AGENTS.md` grows past its budget, or if a relative markdown link in
the entry files does not resolve.

**Consequences:** The structure cannot rot silently while the suite is green.

---

## ADR-009 — Auth is fail-closed and mounted at one choke point
**Date:** 2026-10-21 · **Status:** accepted, implemented

**Context:** Only `/users/*` used `verify_auth`; trading, live, analysis, backtest,
predictions, journal, agents, and monitoring were reachable without a credential.
`API_DEBUG` plus the shipped default key returned a `dev-user-id` bypass.

**Decision:** `backend/main.py` mounts every domain router with
`Depends(verify_auth)`; the auth router is the only public router. `API_DEBUG` never
bypasses auth. An empty/default `api_secret_key` returns 503, comparisons are
constant-time, and JWT decoding is skipped unless `JWT_SECRET_KEY` is non-default.
The local dashboard stores the key in `sessionStorage` and sends `X-API-Key`.

**Consequences:** A misconfigured server refuses traffic instead of serving it
unauthenticated. The default key is not a credential. `/auth/register` is a one-time
bootstrap guarded by the operator's API key: the first account becomes the local
admin; later registrations are 403. `UserRegister` has no `role` field, so clients
cannot choose a privilege level. `/auth/login` returns 503 unless `JWT_SECRET_KEY`
is configured, so it never issues a token that `verify_auth` will reject.
Tests enumerate `/api/v1` routes and fail if one lacks `verify_auth`.

---

## ADR-010 — The kill switch latches closed and requires human re-arm
**Date:** 2026-10-21 · **Status:** accepted, implemented

**Context:** `KillSwitch` caught only `redis.ConnectionError`, returned `False` for
`is_active` on failure, used process-local state in the API, and `arm()` always
cleared the metric even when the Redis delete failed.

**Decision:** The API and runner share one `KillSwitch` backed by Redis. Any
`redis.RedisError`/`OSError` latches `_fail_closed`; `is_active` and `check()` return
blocked, `activate` mirrors the trip locally, and `arm()` refuses to clear while the
store is unavailable. After recovery, only an explicit human `arm()` clears the
latch. `/live/kill` and `/live/arm` work even with no exchange configured.

**Consequences:** A Redis outage halts live orders; it never silently re-enables
them. The UI must show `storage_healthy=false` and the re-arm requirement. A process
restart does not re-arm a tripped switch because state is in Redis.

---

## ADR-011 — Live trading is opt-in at every layer
**Date:** 2026-10-21 · **Status:** accepted, implemented

**Context:** Creating a `LiveTradingEngine` was enough to start it and place orders;
the only visible default was the mode/promotion gate.

**Decision:** `settings.live_trading_enabled` defaults to `false`. The API refuses
`/live/start` and `set_mode(auto|semi)` with 403, `ExecutionAgent` falls back to
paper, and `LiveTradingEngine.start()`/`execute_signal()` refuse at the engine level.
Even when enabled, the kill switch, mode, promotion gate, and exchange connection
must still pass.

**Consequences:** Paper-only is the default in bare-metal and Compose runs. Enabling
live trading requires an explicit environment change plus the existing safety gates;
it is not a single boolean bypass.

---

## ADR-012 — Paper PnL is equity-based, with costs and marks
**Date:** 2026-10-21 · **Status:** accepted, implemented

**Context:** The paper engine filled at the signal price with no costs, valued open
positions at entry, credited shorts as if they were longs, and reported only closed
PnL. The promotion gate could therefore pass on results that ignored fees, adverse
fills, and open-position drawdown.

**Decision:** `PaperTradingEngine` accepts decimal `commission_pct` and `slippage_pct`;
the application wires 10 bps per side from settings, while direct construction
defaults to zero so unit tests can isolate accounting. Longs pay up and sell lower;
shorts receive less and buy back higher. Shorts credit proceeds, report 100% notional
margin, and subtract the liability from equity. When one candle spans both the stop
and target, the engine assumes the stop was reached first rather than taking the
optimistic path. `mark_to_market` records equity on every bar;
`total_pnl = equity - initial_capital`, including unrealized PnL and fees.
The worker marks each candle, persists SL/TP closures to `trade_history`, and on a
closure mirrors the engine snapshot to the portfolio projection. The execution agent
reports and persists the engine's actual fill price and quantity, not the requested
signal.

**Consequences:** Paper results now include costs and intra-trade drawdown. The DB
`positions` table has no side column, so short positions remain an unsigned projection
until the P1 schema/durability work. The in-memory engine is still not durable across
restart.

---

## ADR-013 — Production safety is an explicit Compose overlay
**Date:** 2026-10-21 · **Status:** accepted, implemented

**Context:** `Settings` already refused default secrets when
`environment=production`, but neither Compose file set that value, so the validator
was dormant in the deployment path.

**Decision:** Keep the default Compose files development-oriented. Add
`docker-compose.prod.yml` and `docker/docker-compose.prod.yml` overlays that set
`ENVIRONMENT=production` for the app services. Production startup is therefore an
explicit command:
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
The existing validator remains fail-fast on default API, JWT, and DB secrets.

**Consequences:** Development remains usable without production credentials. A
production deployment that forgets the overlay is visibly a development deployment,
not a silent production one. The overlay does not enable live trading; the live gates
still apply.
