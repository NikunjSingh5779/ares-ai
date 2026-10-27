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

## ADR-005 — One portfolio source of truth (accepted, implemented 2026-10-21)
**Date:** 2026-10-20 · **Status:** accepted, **implemented for paper state**

**Context:** The API kept an in-memory `PaperTradingEngine` while the runner and DB
held separate state. A restart silently reset capital to $100k, and DB position rows
could not represent shorts.

**Decision:** Persist the paper portfolio, positions, orders, closed trades, and equity
curve in PostgreSQL and make every process read/write through one repository
(`paper_trading/repository.py`) behind one service (`paper_trading/ledger.py`). The
in-memory engine remains a hydrated calculation cache. Each fill/mark/closure writes
one transaction; a failed write restores the pre-action cache snapshot. An accepted
fill with no seeded paper account is rejected rather than kept only in memory.

**Consequences:** P1-A is implemented and covered by repository/service/restart tests
plus a manual PostgreSQL 16 round-trip. API reads now hydrate before responding.
Concurrent writes were still last-writer-wins at P1-A; ADR-015 (P1-C) now serializes them.
P1-B added order idempotency. The pipeline result used to be a process-global
`_last_state`; ADR-023 replaces it with a bounded per-session store.

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
The worker and runner process each candle through `PaperTradingLedger`, which persists
SL/TP closures, marks, orders, trade history, and the portfolio together. The raw-SQL
worker path remains only as a fallback for direct-engine callers. The execution agent
reports and persists the engine's actual fill price and quantity, not the requested
signal.

**Consequences:** Paper results now include costs and intra-trade drawdown. P1-A adds
`positions.side`, entry/exit commissions, margin, and a persisted equity curve, so
long/short positions and their cost basis survive restart. The engine still requires
the process to be constructed with the same configured fee/slippage settings; those
settings are configuration, not part of the persisted portfolio state. Concurrent
writers were last-writer-wins through P1-B; ADR-015 (P1-C) now serializes them.

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

---

## ADR-014 — API paper execution requires upstream approvals and idempotency
**Date:** 2026-10-21 · **Status:** accepted, implemented (P1-B, committed)

**Context:** `/execute` accepted a raw `{symbol, side, quantity, entry_price}` body and
called the ledger directly. It required auth but not consensus or Risk approval, and it
had no duplicate-order guard. A caller could therefore create a position that never
passed the agent gates and could retry an ambiguous request into a second position.

**Decision:** `/execute` accepts only an `ExecuteTradeRequest` with a required
`client_order_id` and typed `approval` outputs from Market Analyst, Quant, and Risk
(optional Vision). The server re-runs `ConsensusEngine.evaluate`, requires both agent
confidences >80%, matching directions, `risk.approved=true`, and `risk_score<=70`.
It derives entry price from the approved Market Analyst `current_price`, quantity from
`risk.max_position_size`, and stop-loss from the Risk output. It rejects missing or
non-finite values, a stop on the wrong side of entry, and notional above 2% of current
paper equity. Caller-supplied price/quantity and a manual bypass are not accepted; manual
trades remain a future, separately designed path that must be labeled and excluded from
promotion.

`orders.client_order_id` is unique per paper account through a partial unique index.
The repository checks before mutation, and the index closes the concurrent-retry race.
A duplicate returns **409 Conflict** and never creates a second position. A failed or
conflicting write restores the hydrated cache snapshot.

**Consequences:** A request without approvals cannot create a position, and an ambiguous
retry cannot duplicate a fill. The authenticated API key remains the trust boundary: a
credential holder can still supply synthetic agent outputs, because there is no signed or
expiring signal token yet. This decision did not add row locking or optimistic versions;
concurrent API/worker/runner writers could still lose an update until ADR-015 (P1-C).
Existing
deployments must run `alembic upgrade head` for `0003_order_idempotency`. Generated trades
continue through `/signal`; the frontend wrapper was updated but remains unused by pages.

---

## ADR-015 — Paper writes serialize on a transaction-scoped advisory lock
**Date:** 2026-10-21 · **Status:** accepted, implemented (P1-C, committed)

**Context:** `PaperTradingLedger` did `hydrate → mutate → persist` with no lock. API, worker,
and runner each hold a process-local engine cache, so two processes could hydrate the same
portfolio and then overwrite each other's committed cash, positions, and equity curve.
`client_order_id` (ADR-014) prevents duplicate requests, not lost updates. A single-process
cache also races internally: a reader could re-hydrate the engine between another handler's
mutation and its `persist` call.

**Decision:** Serialize paper writes with two locks taken in the same order:

1. an in-process `asyncio.Lock` in `PaperTradingLedger` around every operation that touches
   the shared cache (writes, refreshes, and reads that hydrate);
2. a PostgreSQL **transaction-scoped** advisory lock (`pg_try_advisory_xact_lock`) in
   `PaperLedgerRepository.writer_lock()`, acquired before hydrate and released by the
   rollback that ends the context manager.

The advisory lock is polled with a bounded timeout
(`PAPER_TRADING_WRITER_LOCK_TIMEOUT_SECONDS`, default 10 s); a writer that cannot acquire it
raises `PaperLedgerBusyError`, which `/execute` maps to **503** with `Retry-After: 1`.
Worker and runner log the error and retry on their next tick.

A session-level lock (`pg_advisory_lock`) was rejected: SQLAlchemy returns a connection to
the pool on `COMMIT`, so the matching unlock can run on a different connection and the lock
then leaks on an idle pooled backend — observed during real-PostgreSQL validation.
Optimistic version columns were rejected as the primary mechanism because they detect
conflicts after the engine has already mutated the cache; the lock prevents the conflicting
read instead.

**Consequences:** API, worker, and runner can no longer lose paper-ledger updates; the second
writer waits and then hydrates the first writer's committed state. No schema change and no
migration. The lock is per database, not per paper account, so unrelated paper accounts (when
seeded) would serialize with each other; acceptable at single-user scale. Throughput is one
paper write at a time, which is far above the platform's 60-second candle cadence. Reads
still hydrate their local cache without the advisory lock, which is safe because caches are
process-local. The pipeline result moved to a per-session store in ADR-023;
role authorization is ADR-016.

---

## ADR-016 - Roles are credential claims; live controls do not depend on the database
**Date:** 2026-10-21 - **Status:** accepted, implemented (P1.6, committed and pushed)

**Context:** Before P1.6, any valid API key or JWT reached `/execute` and every live
control. The database only knew `user`/`admin`/`super_admin`, so there was no read-only
role and no operator tier. A role check that looks the user up in PostgreSQL on every
request would also make `/live/kill` and `/live/arm` fail during a database outage,
exactly when the kill switch is most needed.

**Decision:**
- Canonical roles are `viewer`, `operator`, `admin`, `super_admin`. `viewer` is read-only;
  `operator` and above may execute paper trades and operate live controls; `admin` and
  `super_admin` additionally administer users.
- `POST /auth/login` mints the role into the JWT (`{"sub": email, "role": role}`).
  `require_trading_access` and `require_live_control` verify the JWT signature and read
  the claim directly; they never query PostgreSQL.
- A server API key maps to `admin`, because the key is the server-to-server operator
  trust boundary. A JWT with no role, or an unknown role, fails closed to `viewer`.
- `/api/v1/execute` and `/live/{mode,start,stop,kill,arm}` require `operator` or higher.
  Read-only live routes remain available to viewers.
- Migration `0004_role_hierarchy` expands the database constraint, rewrites legacy `user`
  rows to `operator`, and makes `viewer` the default for new rows.

**Alternatives considered:**
- *Look up the role in PostgreSQL on each request.* Rejected: it makes safety controls
  depend on the database and adds a query to every gated call.
- *Keep `user` as the operator role and add only `viewer`.* Rejected: `user` is ambiguous
  and the migration would still need a compatibility story.
- *Accept the role from a request header or body.* Rejected: a client must never choose
  its own role.

**Consequences:** Role changes take effect on the next login because the role is a claim;
there is no revocation list. Tokens minted before P1.6 have no role claim and are read-only
until re-login. The API key remains a high-trust secret and always maps to `admin`. The
role checks are centralized in `backend/core/dependencies.py`, and the kill switch still
works while PostgreSQL is down. Tests cover the role matrix and viewer denial against the
real routes; migration `0004` was verified on PostgreSQL 16, including a legacy `user` row.

---

## ADR-017 — Compose bootstrap is shared by init.sql and Alembic
**Date:** 2026-10-21 · **Status:** accepted

**Context:** A fresh Compose volume runs `database/init.sql` before the backend starts.
That script creates the current schema, including columns from later revisions. The backend
entrypoint then ran `alembic upgrade head`, whose `0001` re-executed `schema.sql` and failed
on existing tables. Windows checkouts also produced CRLF `backend-entrypoint.sh`, which
Linux rejected with `exec /entrypoint.sh: no such file or directory`. Separately, the
full-stack Compose file interpolated `DATABASE_URL`, `REDIS_HOST`, and `CHROMA_HOST` from
the host-oriented `.env`, so the container tried `localhost`; and the pinned Chroma 0.5.0
server only spoke v1 while the Python client was 1.5.9, with the volume mounted at the
0.5.0 path even though 1.x writes to `/data`.

**Decision:**
- Keep `init.sql` as the fresh-volume schema bootstrap.
- Before `alembic upgrade head`, the entrypoint checks whether `users` exists without an
  `alembic_version` row; if so, it runs `alembic stamp 0001`. The later revisions
  (currently `0002`–`0006`) are idempotent and then bring the database to head.
- Force LF for `*.sh` in `.gitattributes`, and keep `backend-entrypoint.sh` LF in the tree.
- Force container-internal service hostnames in the backend environment. The root `.env`
  remains host-oriented; it is not the container network contract.
- Pin the Chroma server to the client-compatible 1.5.9 image and mount the persistent
  volume at **`/data`**, the 1.x persistence path. The old `/chroma/chroma-data` mount was
  a 0.5.0 convention and would silently discard memory data. The 1.x image has no
  curl/python, so disable its container healthcheck; the backend starts on
  `service_started` and `/health` remains **503** until Chroma answers.

**Alternatives considered:**
- *Delete the `init.sql` mount and let Alembic create everything.* Rejected: it changes the
  first-boot contract and loses the plain-SQL bootstrap used by operators.
- *Make every statement in `schema.sql` idempotent.* Rejected: broad, error-prone, and
  duplicates the migration history.
- *Keep Chroma 0.5.0 and downgrade the Python client.* Rejected: the app already depends on
  the 1.x client and memory tests; the server was the stale side.
- *Add a curl/python healthcheck to the Chroma image.* Rejected: the image does not include
  either tool, and a shell `/dev/tcp` probe is brittle.

**Consequences:** Fresh Compose volumes start cleanly; existing volumes with a version row
are untouched. A database initialized by `init.sql` is stamped at `0001` and upgraded
through the idempotent later revisions. The backend is the readiness authority for Chroma
while the Chroma container is starting. The Phase 1 Compose restart exit passed with this
bootstrap and left the local `.env` key unchanged.

---

## ADR-018 — Dashboard preferences are durable; safety limits stay read-only
**Date:** 2026-10-22 · **Status:** accepted

**Context:** `/settings` was a static page whose save was a `setTimeout`. It displayed a
10% position cap while the execution path enforces 2%, showed a WebSocket endpoint that
does not exist, and rendered a fake secret preview. The Phase 2 exit forbids a page that
renders invented settings. A preference must survive a backend restart, but making risk
limits editable from the dashboard would create a second source of truth for the safety
gate.

**Decision:**
- Persist non-safety preferences in a singleton `app_settings` row (`id = 1`,
  `preferences JSONB`), introduced by migration `0005_app_settings`.
- Expose two preferences that the dashboard actually consumes: `default_symbol` (dashboard
  quick analysis and the initial markets chart) and `live_refresh_seconds` (the `/live`
  poll interval, 5–30 seconds). Unknown fields are rejected.
- `GET /api/v1/settings` returns read-only safety values computed from the enforcing
  modules (`agents.risk`, `agents.consensus`) and `configs.settings`.
- `PUT /api/v1/settings/preferences` accepts only `DashboardPreferences`. A `safety`
  object, position cap, confidence threshold, drawdown limit, or promotion-gate field is a
  **422**, never a write.
- Remove the unused `MAX_POSITION_SIZE_PCT` environment field. The 2% cap lives only in
  `agents/risk.py`, so an env edit cannot silently raise it.

**Alternatives considered:**
- *Store preferences in `localStorage`.* Rejected: the requirement is a durable API
  round-trip, and a browser-local value is not shared by the API or a second process.
- *Add a per-user `users.preferences` column.* Rejected for now: the dashboard uses the
  shared API key, which has no user row, and the deployment is single-user. A singleton
  row is the honest scope; per-user preferences would need a user resolution path first.
- *Make the position cap editable within 0–2%.* Rejected: the signal path, `/execute`
  route, and risk agent would all need to read the same runtime value consistently. A
  partially applied cap is worse than a fixed, tested one.
- *Keep the old `MAX_POSITION_SIZE_PCT` env field and align it to 2%.* Rejected: it would
  still be a dead duplicate that invites an operator to think the cap is tunable.

**Consequences:** Settings survive a process restart and the API proves the round-trip.
Safety values cannot be raised through this endpoint. Preferences are global, matching the
single-user deployment; a future multi-user mode needs an explicit user-scoped store.
Adding a preference is a schema-free JSONB change, but every new field must be consumed by
a page or it does not belong in the response.

---

## ADR-019 — Strategy drafts reuse `strategies`; lifecycle fields stay server-owned
**Date:** 2026-10-22 **Status:** accepted

**Context:** The strategy-builder page had a `setTimeout` save and never persisted
anything, while the database already had a `strategies` table with type, config,
parameters, version, status, promotion counters, and `live_trading_enabled`. Adding a
second draft table would duplicate that shape; allowing the browser to set status or
live enablement would create a shortcut around the promotion gate.

**Decision:**
- Use the existing `strategies` table and add no migration or schema change.
- Expose only draft configuration through authenticated `GET/POST/PUT
  /api/v1/strategies`; create always lands as the table default `draft`.
- `StrategyCreate`/`StrategyUpdate` use `extra="forbid"`. `status`,
  `live_trading_enabled`, and promotion counters are **422** and never written.
- Edit only rows whose stored status is `draft` or `paused`; all other statuses are
  **409**. An edit bumps `version` and leaves lifecycle fields alone.
- Treat `position_size_pct`, `stop_loss_pct`, and `take_profit_pct` as draft inputs, not
  safety limits. Risk, consensus, promotion, execution, and the kill switch remain
  authoritative.
- Hand a draft type to the backtest page only when the backtest engine supports it;
  unsupported types fail honestly instead of sending an invalid run.

**Alternatives considered:**
- *Add a `strategy_drafts` table.* Rejected: duplicates the existing schema and splits
  strategy history.
- *Let the client set `status` and `live_trading_enabled` in the same request.* Rejected:
  that would bypass the promotion gate and the human approval path.
- *Use `localStorage`.* Rejected: drafts must survive a browser and process restart and
  be readable by a second client.
- *Make every draft editable, including paper/live rows.* Rejected for now: editing a
  live strategy in place changes behavior without a promotion record.

**Consequences:** Drafts survive restarts and the UI has a real save/load path. Promotion
remains a separate gated process; a future feature that edits paper/live strategies needs
an explicit versioned-copy or approval design. The strategy service uses the proven
JSONB/`RETURNING` pattern; a disposable-PostgreSQL round-trip for the new routes remains a
follow-up test.

---

## ADR-020 — Chat is stateless, read-only, and client-held
**Date:** 2026-10-22 **Status:** accepted

**Context:** `/chat` called `POST /api/v1/analyze` and displayed the accepted status,
so it was a pipeline trigger with a chat skin, not a conversation. A real assistant
needs prior turns and a model call, but the platform's safety boundary says chat must
never become a second order path. The deployment is single-user with a shared API key
and no guaranteed user row.

**Decision:**
- Add `POST /api/v1/chat` with a bounded `ChatRequest` (1–20 turns, 1–4000
  characters, last turn from the user, `extra="forbid"`).
- Keep history client-held and stateless on the server; no conversation table and no
  server-side memory. The page sends the recent turns each time.
- Use the standard fallback router with a `chat` entry in `configs/models.yaml`; all
  IDs are free-tier. Return `{reply, model, fallback_used}`.
- Give the service no tools and no execution path. The system prompt forbids orders,
  mode/kill-switch changes, promotion, fabricated trading data, secret requests, and
  bypassing safety gates.
- Return **503** if the chain is exhausted, the response is an error envelope, or the
  text is empty. Never fabricate a reply.
- Do not stream in this slice; a non-streaming request is simpler to validate and
  keeps the error/fallback path explicit.

**Alternatives considered:**
- *Reuse `/analyze` and poll the pipeline.* Rejected: the pipeline is a trading
  analysis, not a conversation, and its state is global.
- *Persist conversations in PostgreSQL.* Rejected for now: the shared API key has no
  user row, and a conversation table adds retention/privacy scope without a product
  requirement. Client-held history is honest for a single-user dashboard.
- *Give chat tools to query portfolio/orders.* Rejected: that creates a second data
  path with its own authorization and freshness problems; the read-only UI pages
  already show that data.
- *Stream tokens.* Deferred: the fallback chain and empty/error handling are the
  valuable parts; streaming can be added behind the same schema later.
- *Let chat trigger an analysis.* Rejected: it would blur the explicit Analyze action
  and could be mistaken for trade authorization.

**Consequences:** Multi-turn context works without new state or migrations. A reload
starts a new thread; there is no server-side transcript. Chat is a guide, not a trading
operator, and a model outage fails closed with 503. Streaming and conversation
persistence remain explicit future work.

## ADR-021 — Local chat is opt-in, separate, and process-wide gated
**Date:** 2026-10-23 **Status:** accepted

**Context:** Operators can run an OpenAI-compatible model locally. The local server is
useful as a free fallback, but it usually serves one generation at a time, is not part
of the remote free-tier catalog, and must not make the pipeline depend on a workstation
being available. The remote `chat` chain's free-tier assertion must stay honest.

**Decision:**
- Add a separate `local_chat` roster entry with a `local/` model ID. Do not insert local
  IDs into the remote `chat` chain or the universal fallback. The remote chain remains
  free-tier only.
- Make local use opt-in with `LOCAL_LLM_ENABLED=false`. Add a configurable base URL,
  timeout, concurrency, and queue timeout; bundle no model and start no download.
- Strip `local/` before the HTTP request, send no `Authorization` header, and request
  `reasoning_effort="off"` so reasoning tokens do not consume the chat budget.
- Gate local calls in `ModelRouter` with one process-wide semaphore, default
  `max_concurrent=1`. A busy local candidate is skipped without retry or breaker
  failure and the chat route returns **503** if no fallback answers.
- Use local as an appended chat fallback when a remote provider is configured and as
  the only chat chain when none is. Keep pipeline agents remote for now.
- In Compose, reach a host-run server through `host.docker.internal`; for a host-run
  backend, use loopback.

**Alternatives considered:**
- *Replace the remote chat chain with local.* Rejected: local availability would become
  a hard dependency and the free-tier roster check would no longer describe chat.
- *Enable local for every agent.* Rejected for now: schema compliance and latency are
  unproven; chat is the lowest-risk scope.
- *Gate per router instead of per process.* Rejected: chat and analysis can each hold a
  router, so per-router limits could still overlap on the single local server.
- *Wait indefinitely for a local slot.* Rejected: a blocked request hides overload.
  A bounded wait then 503 is explicit.
- *Bundle the model or download it on first use.* Rejected: multi-GB artifacts and
  silent network activity are not acceptable defaults.
- *Add live web/news retrieval to improve local answers.* Rejected: chat stays read-only
  and tool-free.

**Consequences:** Local chat is usable without weakening the remote chain or safety
gates. The gate is per process, not a distributed lock, and local chat remains
chat-only. A live smoke test is manual because CI has no model server; one passed
against Strata on 2026-10-24 (direct 0.49 s, ChatService 0.99 s, local-only, and
`POST /api/v1/chat` returned 200).

## ADR-022 — Improvement history is durable; suggestions stay advisory
**Date:** 2026-10-24 **Status:** accepted

**Context:** The improvement engine analyzed a process-local reflection list. A restart
erased trend context, a second worker had a different view, and the API returned an empty
list in normal operation because the pipeline never called `analyze()`. Reflection output
was persisted only as human-readable journal text, so the engine's numeric fields could
not be queried across runs.

**Decision:**
- Add `reflection_runs` for structured reflection output and `improvement_records` for
  generated suggestions, with indexes and a unique
  `(reflection_run_id, category, description)` retry guard. Migration
  `0006_improvement_history` owns both tables.
- Give engine records UUIDs so they map directly to the PostgreSQL primary key and cannot
  collide when two runs finish in the same millisecond.
- Let `StrategyImprovementEngine.analyze()` accept an explicit oldest-first history
  window. In that mode it must not mutate process globals; the persistence service owns
  committed history and passes the window.
- Persist in one async transaction: insert the reflection run, load the last 100
  committed runs excluding that row, analyze, insert generated records, commit. Roll
  back on any failure.
- Invoke persistence from an optional `Supervisor.post_run_hook` after `log_execution`
  in both `run` and `stream_analysis`. The hook is best-effort with a 5 s timeout; it
  logs and swallows failures and never changes the pipeline result. Wire it in
  `/api/v1/analyze` and `scripts/run_live.py`; do not record backtest history.
- Make the improvement API PostgreSQL-backed. A store failure is **503**; an unknown or
  malformed record ID is **404**; `apply` only marks `applied`/`applied_at`.
- Keep suggestions advisory. No generated or applied record may mutate a threshold,
  position cap, drawdown limit, promotion gate, or the kill switch.

**Alternatives considered:**
- *Reuse the `journal` table's JSON/text.* Rejected: the engine needs typed numeric and
  list fields across runs; journal prose is for humans and has a different lifecycle.
- *Keep the process-global history and add a background flusher.* Rejected: restarts and
  multiple workers still lose or diverge from history, and the API would remain
  process-dependent.
- *Make improvement a LangGraph node.* Rejected: a history outage could fail or delay a
  completed trade run. The post-run hook keeps history off the decision path.
- *Write history inside `ReflectionAgent`.* Rejected: analyst agents do not own database
  access, and coupling the agent to persistence makes failure semantics unclear.
- *Scope history per symbol or strategy now.* Rejected for this slice: the deployment is
  single-user and the engine is a global strategy review. Scoping needs an explicit owner
  column and a product decision.

**Consequences:** Improvement trends survive restarts and multiple workers, and the API
returns real history. The hook is intentionally lossy during a database outage; that run
is skipped and the trade result is unchanged. History is global across symbols, and
suggestions are not linked to the exact config field they would change, so an operator
must map a suggestion to a parameter before editing configuration.

---

## ADR-023 — Analysis runs are bounded and state is per session

**Status:** accepted 2026-10-28.

**Context:** `POST /api/v1/analyze` installed a module-global `_last_state` and scheduled
`BackgroundTasks` without a bound. Two concurrent runs raced and the last writer won;
`/agents/status` and `/risk` could show a different run than the caller had started.
A burst of requests could schedule an arbitrary number of multi-agent pipelines, each
making many free-tier LLM requests, and nothing stopped a stuck pipeline.

**Decision:**
- Add `backend/services/analysis_control.py` with an `AnalysisStateStore` keyed by
  `session_id`. The store is capacity-bounded and selects the most recently *started*
  run for the dashboard default; an older run can still update its own session.
- Add an `AnalysisGate` shared by `/analyze`, `/analyze/stream`, and `/signal`. It holds
  a process-wide semaphore (`ANALYSIS_MAX_CONCURRENT`, default **1**), rejects a start
  with **429** when no slot is free (background/stream) or after a bounded wait
  (`ANALYSIS_QUEUE_TIMEOUT_SECONDS`), and enforces a rolling
  `ANALYSIS_MAX_RUNS_PER_HOUR` budget. On the free tier the run count is the meaningful
  unit of model spend; there is no dollar budget to enforce.
- Bound every accepted run with `ANALYSIS_TIMEOUT_SECONDS` (default **300**) as a
  **stage-start deadline**, not an outer cancellation of the graph. The supervisor checks
  the deadline before `analysis_and_vision`, `quant`, `news`, `risk`, and `execution`, and
  wraps each LLM call in the remaining time. Once `execution` starts, the deadline is
  cleared so journal, reflection, memory, and post-run logging always finish; a timeout
  must never cancel a paper/live fill after the ledger or broker accepted it and turn it
  into a retryable response. Release the slot and record a terminal state on success,
  failure, timeout, or cancellation. A synchronous `/signal` timeout returns **504** only
  for `AnalysisDeadlineExceededError` raised before execution starts; a plain `TimeoutError`
  from logging or the database is a failure (**500**), because execution may already have
  committed a fill.
- Release the gate through an idempotent `AnalysisLease`. `/analyze` installs a
  done-callback so a task cancelled before its coroutine starts cannot leak the slot;
  `/analyze/stream` releases from the response wrapper even when the body iterator is
  never started. Both paths also mark the placeholder terminal and record `cancelled`
  when the run never began, so the dashboard cannot show a permanently pending run.
- Keep `ANALYSIS_STATE_CACHE_SIZE` entries (default **64**) in start order and expose
  `GET /api/v1/agents/status?session_id=...` for a specific run; without the parameter it
  reads the latest started run, preserving the dashboard contract.
- Record `ares_analysis_runs_total{status}` (including `rejected_busy`, `rejected_budget`,
  and `setup_failed`) and `ares_analysis_in_flight` so rejected, timed-out, and cancelled
  runs are visible in Prometheus.

**Alternatives considered:**
- *Queue every request behind the semaphore.* Rejected: a burst would create an
  unbounded backlog of background tasks that might start minutes later. Fail closed with
  **429** instead.
- *Share the gate through Redis now.* Deferred: the Compose stack runs one uvicorn
  worker. The store and gate are deliberately process-local, like the metrics registry
  and paper cache; multi-worker needs a shared implementation.
- *Enforce a token or dollar budget.* Rejected for this slice: the roster is free-tier
  and the pipeline does not aggregate provider usage. A run-count budget bounds the same
  spend without a fragile per-token estimate.
- *Keep one global and add a lock.* Rejected: a lock serializes writers but still leaves
  no way to read the run a caller started, and it does not bound the work.

**Consequences:** Concurrent analysis is explicitly serialized by default; callers that
need more throughput can raise `ANALYSIS_MAX_CONCURRENT`, at the cost of more concurrent
LLM traffic. A run that spends the whole deadline before execution is rejected without a
fill; a run already in execution finishes and reports its real result. The budget and
in-flight count reset on process restart, and a multi-worker deployment would need a
shared store. The safety gates, kill switch, and promotion logic are unchanged; this ADR
only bounds how analysis work is scheduled and where its result lives.
