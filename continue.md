# CONTINUE.md — ARES AI handoff

**Last updated:** 2026-10-21
**Repository:** `C:\Users\ASUS\ares-ai`
**Branch:** `fix/orchestration-reliability-frontend`
**Head commit:** `4605162 feat: add MCP server configuration and integrity check file`
**Branch position:** 1 commit ahead / 4 behind `master` (per `git rev-list --left-right --count master...HEAD`).
**Working tree:** intentionally **dirty and uncommitted**. It contains previous P0 work plus this session's work. Do not reset, clean, commit, or push unless the user explicitly asks.

This file is the fresh-session handoff. Read it fully before editing. It records:
- what was completed,
- what was verified,
- the exact behavior contracts that must not regress,
- the remaining defects,
- the recommended order of work,
- concrete commands and traps.

---

## 0. TL;DR

The P0 safety phase is complete:

1. Auth is required on every non-public route.
2. There is one live-order path; live trading is paper-only by default.
3. The kill switch is fail-closed and requires human re-arm.
4. The free-model roster has a universal fallback.
5. Paper accounting now has commissions, adverse slippage, mark-to-market, short proceeds/margin, and equity-based PnL.
6. Production Compose overlays activate the existing fail-fast secret validator.
7. Consensus now requires **strictly greater than 80%**, as the spec says.

The next release blocker is **Phase 1: one durable source of truth**. Today the paper engine is in memory; the API process and runner process have separate engine instances; the DB portfolio is a projection; `positions` cannot store long/short; a restart loses capital and open positions.

**Do not start new feature work before reading sections 2, 3, 7, and 8.**

---

## 1. Fresh-session start checklist

Run these first from the repository root:

```powershell
cd C:\Users\ASUS\ares-ai
git branch --show-current
git status --short
git rev-list --left-right --count master...HEAD
```

Read in this order:

1. `AGENTS.md` — routing only.
2. `docs/01-SPEC.md` — the mandate and hard rules.
3. `docs/02-STATUS.md` — verified state and known gaps.
4. `docs/05-NEXT.md` — ordered plan.
5. `docs/03-ARCHITECTURE.md` — layers/data ownership.
6. `docs/04-DECISIONS.md` — ADRs 001–013.
7. This file.
8. The relevant folder `CONTEXT.md` before editing that folder.

Useful paths:

| Area | Read | Edit |
|---|---|---|
| Paper engine | `paper_trading/CONTEXT.md` | `paper_trading/engine.py`, `paper_trading/worker.py` |
| Execution | `agents/CONTEXT.md` | `agents/execution.py` |
| API | `backend/CONTEXT.md` | `backend/routers/trading.py` |
| Config | `configs/CONTEXT.md` | `configs/settings.py`, `.env.example` |
| Live safety | `live_trading/CONTEXT.md` | `live_trading/engine.py`, `live_trading/safety.py` |
| Schema | `database/CONTEXT.md` | `database/init.sql`, `database/schema.sql`, migrations |
| Tests | `tests/CONTEXT.md` | `tests/**` |
| Deployment | `docker/CONTEXT.md` | `docker-compose.yml`, production overlays |

Then run the baseline checks:

```powershell
python -m pytest tests/ -q
ruff check .
ruff format --check .
mypy .
```

Expected today:

- `pytest`: **1044 passed**, 2 warnings, **79.08%** coverage, exit 0.
- `ruff`: clean.
- `mypy`: **22 pre-existing errors in 8 test/script files**. Production code is currently clean under mypy.
- Do not claim mypy is green until those 22 are fixed.

Frontend:

```powershell
cd frontend
pnpm build
```

Expected today: passes on Next.js 16.2.12.

`pnpm lint` currently fails because the script is still `next lint`, which Next 16 rejects as a directory. This is pre-existing; fix it as part of the frontend/CI work, or use a real ESLint invocation after adding config.

**Security trap:** do **not** run plain `docker compose config` in a captured terminal. It can print local `.env` secrets. If you need to validate Compose, use `config --quiet` with temporary dummy environment values and do not print the resolved config.

---

## 2. Non-negotiable rules

These are from `AGENTS.md`, `docs/01-SPEC.md`, and the user's instructions.

1. **Free-tier models only.** Model IDs live only in `configs/models.yaml`, never hardcoded in agents.
2. **Every agent input/output is typed** with Pydantic; `rationale` is required wherever a trading number is produced.
3. **No signal = no trade.** A required agent failure rejects the trade; it never silently approves.
4. **Market Analyst and Quant must both be strictly above 80% confidence**, directions must agree, Risk must approve, and drawdown/exposure must be safe.
5. **Live trading starts in human-approval mode.** Autonomous mode is opt-in per strategy only after the paper-trading promotion gate.
6. **A kill switch must halt order placement and require human re-arm.** Never bypass a safety gate.
7. **Never hardcode or commit secrets.** `.env.example` only; `.env` stays untracked.
8. **Model failure degrades gracefully** and is logged with the fallback used.
9. **Definition of done:** tests pass, `ruff` + `mypy` clean, docs updated in the same change.
10. **Never weaken a safety gate to make a test pass.**
11. **Do not modify** `C:\Users\ASUS\.claude\plugins` or `C:\Users\ASUS\.claude\skills`; read-only use is allowed.
12. **No real-capital live trading.** Live code stays gated; do not enable it.
13. **Do not commit/push** unless the user explicitly asks. The current work is uncommitted.
14. User preference: dashboard is single-user/local. Future market data direction: existing ingestion + Binance WebSocket + Alpaca.
15. Use ICM/MVC structure and React/frontend review skills for frontend work.

---

## 3. Current verified state

### 3.1 Branch / worktree

- Branch: `fix/orchestration-reliability-frontend`
- 1 ahead / 4 behind `master`
- Prior notes say PR #73 is already in `master`; do not rely on that without checking if it matters.
- The working tree contains 70+ modified/untracked paths from the P0 work and the ICM restructure. This is normal for this handoff; do not discard them.
- No commit, push, PR, or merge was performed this session.

### 3.2 Verified commands and results

| Check | Result |
|---|---|
| `python -m pytest tests/ -q` | **1044 passed**, 2 warnings, exit 0 |
| Coverage | **79.08%**, gate is 78% |
| `ruff check .` | clean |
| `ruff format --check .` | clean |
| `mypy .` | **22 errors in 8 files**, all pre-existing tests/scripts |
| `pnpm build` in `frontend/` | passed |
| `docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` | passed with dummy env |
| `docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` from `docker/` | passed with dummy env |
| Safety gates weakened | none |

The 22 mypy errors are in:

- `tests/test_test_free_models.py` (6)
- `tests/test_error_handlers.py` (4)
- `tests/test_analysis_router.py` (3)
- `tests/test_paper_trading_worker.py` (3)
- `tests/test_supervisor.py` (2)
- `scripts/test_free_models.py` (2)
- `tests/test_live_trading/test_safety_edge_cases.py` (1)
- `tests/test_live_trading/test_engine_edge_cases.py` (1)

Do not report mypy as green. Do not add new production-code mypy errors while fixing those.

---

## 4. What was done this session

### 4.1 P0-4 — realistic paper accounting

**File:** `paper_trading/engine.py`

- `PaperTradingEngine` accepts:
  - `commission_pct`
  - `slippage_pct`
- Constructor defaults are **0.0 / 0.0** so direct unit-test engines remain deterministic.
- The application engine is wired with **10 bps commission + 10 bps slippage** from `configs/settings.py`.
- Entry fills apply adverse slippage:
  - long pays `entry_price * (1 + slippage_pct)`
  - short receives `entry_price * (1 - slippage_pct)`
- Exit fills apply adverse slippage:
  - long sells lower
  - short buys higher
- Commissions are charged on entry and exit.
- `total_pnl = equity - initial_capital`, so open marks and fees count.
- `mark_to_market(symbol, price)` updates `_last_prices` and appends equity.
- Longs are limited by free cash and by equity not reserved as short margin.
- Shorts:
  - credit proceeds to cash,
  - report **100% notional margin** in `margin_used`,
  - subtract the short liability from equity.
- Closed trades carry `entry_commission` and `exit_commission`, plus a derived `fees` field in API/trade dicts.
- If one candle spans both stop-loss and take-profit, the engine now assumes **stop-loss was reached first**. This is conservative and prevents optimistic paper results. Tests were updated accordingly.

**Important accounting example:**

- Initial capital `$100,000`
- Short 10 ETH at `$3,000`
- Cash becomes `$130,000`
- `margin_used = $30,000`
- Equity remains `$100,000`
- Mark at `$2,700`: equity `$103,000`, PnL `$3,000`
- Close at `$2,700`: cash/equity `$103,000`, margin `0`

### 4.2 Application wiring

**File:** `backend/routers/trading.py`

- `_get_engine()` passes `paper_trading_commission_pct` and `paper_trading_slippage_pct` from settings.
- `/api/v1/portfolio` exposes `equity` and `margin_used`.
- `/api/v1/positions` exposes `entry_commission` and `margin`.
- `/api/v1/orders` exposes entry/exit commissions and total fees.

**File:** `configs/settings.py`

- Added:
  - `paper_trading_commission_pct: float = Field(default=0.001, ge=0.0, lt=1.0)`
  - `paper_trading_slippage_pct: float = Field(default=0.001, ge=0.0, lt=1.0)`
- 0.001 = 10 bps, decimal fraction, not percent.

**File:** `.env.example`

- Added `PAPER_TRADING_COMMISSION_PCT=0.001`.
- Added `PAPER_TRADING_SLIPPAGE_PCT=0.001`.

### 4.3 Execution agent — actual fill/size

**File:** `agents/execution.py`

- Paper execution now reads the engine's returned:
  - `fill_price`
  - `quantity`
  - `commission`
- It reports the actual fill/quantity in `ExecutionOutput` (`filled_quantity` included).
- It persists the actual fill/quantity to `positions`.
- Reversal `trade_history` rows map engine `long`/`short` to DB `buy`/`sell`.
- Live branch still goes through `LiveTradingEngine.execute_signal()` only.
- Agent live branch is gated by:
  - `settings.live_trading_enabled`
  - engine running
  - engine connected
  - `TradingMode.AUTO`
  - promotion gate passed

### 4.4 Worker — marks, closures, promotion records, schema fixes

**File:** `paper_trading/worker.py`

- Each tick:
  1. gets latest candle,
  2. checks SL/TP **first** (so a stop fill is not preceded by a worse close mark),
  3. marks any remaining open position at candle close.
- On a closure:
  - updates the `positions` row,
  - mirrors the engine snapshot into `portfolio`,
  - inserts a `trade_history` row,
  - inserts an `orders` row.
- Fixed real schema mismatches that mocked tests would not catch:
  - Removed `positions.side` — the table has no side column.
  - Removed `positions.realized_pnl` — the table has no such column.
  - Replaced `orders.strategy_name` / `orders.reason` — those columns do not exist; the rationale is now written to `orders.agent_rationale` as JSONB.
- `trade_history` uses `buy`/`sell`; engine uses `long`/`short`.
- The portfolio row is still a **projection** of the engine, not the source of truth. It is synced only when the worker closes a trade.

### 4.5 Production configuration

New files:

- `docker-compose.prod.yml`
- `docker/docker-compose.prod.yml`

Both set:

```yaml
ENVIRONMENT: production
```

Root backend also sets:

```yaml
API_DEBUG: "false"
```

Result:

- Development files remain development-oriented.
- Production startup is explicit:
  ```powershell
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
  ```
- `Settings` validates production and refuses default:
  - `API_SECRET_KEY`
  - `JWT_SECRET_KEY`
  - password embedded in `DATABASE_URL`
- The overlay does **not** enable live trading.
- `tests/test_config.py` checks the overlays.
- `docker compose ... config --quiet` passed with dummy env values.

### 4.6 Consensus threshold fix

**File:** `agents/consensus.py`

- Changed:
  - from `>= REQUIRED_CONFIDENCE`
  - to `> REQUIRED_CONFIDENCE`
- Exactly 80.0% is now rejected.
- Updated rationale text to say `need > 80%`.
- `tests/test_consensus.py` boundary test now expects rejection.
- This matches `docs/01-SPEC.md` and hard rule #4.

### 4.7 API/frontend

**File:** `frontend/src/types/api.ts`

- `PortfolioSummary` gained optional `equity` and `margin_used`.
- `OpenPosition` gained optional `entry_commission` and `margin`.
- `ClosedTrade` gained optional `entry_commission`, `exit_commission`, and `fees`.

**File:** `frontend/src/app/portfolio/page.tsx`

- Added an Equity metric.
- Kept Cash Balance.
- Shows reserved short margin when `margin_used > 0`.
- Grid is now five columns on large screens.

### 4.8 Tests added/changed

- `tests/test_paper_trading.py`
  - fee/slippage entry and exit,
  - intra-trade mark-to-market drawdown,
  - profitable short cash/margin/PnL reconciliation,
  - conservative stop-first behavior when both levels are touched.
- `tests/test_paper_trading_worker.py`
  - marks open positions on a non-triggering candle,
  - writes `trade_history` and portfolio snapshot on closure,
  - guards against the exact SQL schema mistakes fixed above.
- `tests/test_execution_agent.py`
  - actual slipped fill and capped quantity,
  - persistence of actual fill/quantity,
  - reversal persistence uses `buy`/`sell`.
- `tests/test_config.py`
  - paper accounting defaults,
  - production overlays set `ENVIRONMENT=production`.
- `tests/test_consensus.py`
  - exactly 80% is rejected.

### 4.9 Docs updated

- `docs/02-STATUS.md` — verified counts, P0-4/P0-5/consensus evidence, renumbered gaps.
- `docs/03-ARCHITECTURE.md` — paper flow and data ownership.
- `docs/04-DECISIONS.md` — ADR-012 paper accounting, ADR-013 production overlay.
- `docs/05-NEXT.md` — Phase 0 closed; Phase 1 next; removed already-fixed consensus item.
- `docs/map/objects/portfolio.md` — new fields, invariants, gaps.
- `docs/map/processes/execution.md` — paper path and promotion source.
- `paper_trading/CONTEXT.md` — fees, marks, short accounting, stop-first rule.
- `configs/CONTEXT.md` — paper cost settings, production overlay.
- `live_trading/CONTEXT.md` — updated promotion/durability caveat.
- `README.md` — production overlay command.
- `.env.example` — paper cost settings.

---

## 5. Behavior contracts that must not regress

These are deliberate decisions, not accidents. If you change them, update tests and ADRs.

### 5.1 Paper engine

- Direct `PaperTradingEngine()` defaults: `commission_pct=0.0`, `slippage_pct=0.0`.
- Application engine defaults: `0.001` commission and `0.001` slippage.
- `total_pnl` is equity-based, not closed-trade-only.
- Shorts:
  - cash includes proceeds,
  - `margin_used` reports 100% notional,
  - equity subtracts the short liability.
- A candle that hits both SL and TP resolves to **stop-loss first**.
- `mark_to_market` appends equity; `check_sl_tp` closes at the threshold and applies exit slippage/commission.
- `close_position` removes the position, updates cash/equity, and appends a `ClosedTrade`.

### 5.2 Worker / DB

- The worker checks exits before marking.
- The worker writes SL/TP closures to `trade_history`; the promotion gate reads `trade_history`, not `paper_trades`.
- `paper_trades` exists but is unused.
- `positions` has **no** `side` column.
- `positions` has **no** `realized_pnl` column.
- `orders` has **no** `strategy_name` or `reason` column; use `agent_rationale` JSONB.
- The portfolio DB row is a projection, synced on worker closure only.
- Do not add SQL columns to a query without checking `database/init.sql` and `database/schema.sql`.

### 5.3 API / execution

- `agents/execution.py` must persist the actual engine fill and quantity, not the requested signal.
- `trade_history.side` is constrained to `buy`/`sell`.
- `positions` rows are currently unsigned; this is a known gap.
- `/api/v1/execute` currently calls the engine directly and bypasses consensus/risk. This is a known P1 gap, not an approved pattern for live trading.

### 5.4 Production

- Production uses an explicit overlay.
- Base development Compose files do not set `ENVIRONMENT=production`.
- The overlay does not enable live trading.
- Do not put secrets in Compose files or docs.
- Do not run plain `docker compose config` in captured output.

### 5.5 Consensus

- Market Analyst **> 80%**.
- Quant **> 80%**.
- Directions agree and are non-flat.
- Risk approves.
- Exactly 80.0% is not enough.

---

## 6. Files changed by this session

Directly touched:

- `paper_trading/engine.py`
- `paper_trading/worker.py`
- `agents/execution.py`
- `agents/consensus.py`
- `configs/settings.py`
- `backend/routers/trading.py`
- `frontend/src/types/api.ts`
- `frontend/src/app/portfolio/page.tsx`
- `tests/test_paper_trading.py`
- `tests/test_paper_trading_worker.py`
- `tests/test_execution_agent.py`
- `tests/test_config.py`
- `tests/test_consensus.py`
- `.env.example`
- `docker-compose.prod.yml` (new)
- `docker/docker-compose.prod.yml` (new)
- `README.md`
- `docs/02-STATUS.md`
- `docs/03-ARCHITECTURE.md`
- `docs/04-DECISIONS.md`
- `docs/05-NEXT.md`
- `docs/map/objects/portfolio.md`
- `docs/map/processes/execution.md`
- `paper_trading/CONTEXT.md`
- `configs/CONTEXT.md`
- `live_trading/CONTEXT.md`

The working tree also contains earlier uncommitted work in auth, live safety, model roster, frontend auth, ICM docs/CONTEXT files, and tests. Do not treat those as this session's changes or revert them.

---

## 7. Known gaps — exact next targets

### Gap 1 — Two portfolio sources of truth (P1, highest priority)

Evidence:

- `backend/routers/trading.py` owns an in-memory `_engine` singleton.
- `scripts/run_live.py` imports `_get_engine` but runs in a separate process, so it has its own instance.
- `paper_trading/worker.py` mirrors the engine into the DB only when it closes a trade.
- Entry/reversal persistence from `agents/execution.py` does not update the portfolio row.
- Restart resets capital and open positions.

Consequence: `/portfolio`, `/positions`, `/orders`, the worker, the runner, and the promotion gate can disagree.

### Gap 2 — `positions` cannot represent shorts (P1)

- `database/init.sql` `positions` table has no `side` column.
- Long/short exists in the engine, API, and `trade_history`, but DB position rows are unsigned.
- Do not “fix” this by adding `AND side=:side` to worker SQL; that was one of the actual bugs fixed this session.
- Add the column through a migration, backfill existing rows, and update every SQL read/write.

### Gap 3 — Direct `/execute` bypasses consensus/risk (P1)

- `backend/routers/trading.py` `/execute` parses a raw body and calls `PaperTradingEngine.execute_signal`.
- It does not require an approved signal or risk output.
- It is paper-only today, so it cannot spend real capital, but it can distort promotion statistics.
- Decide explicitly:
  - preferred: require an approved signal/risk payload and route through the execution contract; or
  - document and enforce it as a manual paper-trade endpoint, excluded/labeled in promotion accounting.
- Add an idempotency key before exposing it broadly.

### Gap 4 — Schema/migration drift (P1)

- `migrations/versions/` is gitignored.
- There are two Alembic heads with `down_revision=None`.
- `database/schema.sql` duplicates `database/init.sql`.
- Mocked tests missed worker SQL referencing nonexistent columns.
- Next session should consolidate schema sources and add a real Postgres integration test.

### Gap 5 — `mypy` red (P1 CI)

- 22 errors in 8 test/script files (list in section 3.2).
- Production code is clean.
- Fix these before calling CI green.
- Add mypy to CI once green.

### Gap 6 — No role-based auth on live/trading routes (P1)

- Any valid API key or JWT reaches live controls.
- Single-user bootstrap limits exposure, but a seeded non-admin JWT is operator-level.
- Add roles (`admin`, `operator`, `viewer`) and require operator/admin for live controls.

### Gap 7 — Kill-switch latch is process-local (P1 operational)

- A Redis outage latches each process.
- `/live/arm` clears the API process, but a runner that also latched stays blocked until restarted.
- This is fail-closed and safe, but operationally awkward.
- Implement a shared arm epoch/generation in Redis and test multi-process recovery.

### Gap 8 — `/analyze` concurrency/cost control (P1)

- Global `_last_state`.
- Unbounded `BackgroundTasks`.
- Runs are not isolated and can rewrite each other's state.
- Add per-run IDs, a semaphore/queue, timeouts, cancellation, and a cost budget.

### Gap 9 — Frontend mock data / lint (P2)

- `frontend/src/app/markets/page.tsx` uses `Math.random()` candles.
- `settings/page.tsx` does not persist through the API and shows fake values.
- `pnpm lint` fails because `next lint` is invalid under Next 16.
- Wire real endpoints, remove invented data, and add a working ESLint command.

### Gap 10 — Model catalog CI (P2)

- `scripts/test_free_models.py` exists but is manual.
- Add a scheduled or CI catalog-validation job.

### Gap 11 — Paper realism beyond P0-4 (P2)

Current model still has:
- stop fills at the stop price even if the candle gapped through it,
- no partial fills/liquidity,
- no borrow/funding cost for shorts,
- one global slippage setting,
- no persisted equity curve.

These are acceptable for the current milestone but must be documented before claiming high-fidelity paper results.

---

## 8. Recommended next work, in order

### P1-A — Durable paper ledger (do this first)

**Goal:** restart the stack mid-trade; portfolio, open positions, and promotion record are identical before and after.

Suggested implementation:

1. **Schema**
   - Add `side` to `positions`:
     ```sql
     side VARCHAR(10) NOT NULL DEFAULT 'long'
         CHECK (side IN ('long', 'short'))
     ```
   - Add it through Alembic, not only `init.sql`.
   - Backfill existing rows as `long`.
   - Update `database/init.sql` and `database/schema.sql` consistently.
2. **Repository**
   - Create `paper_trading/repository.py` (or equivalent).
   - It owns loading and persisting:
     - initial capital,
     - cash,
     - open positions (including side, marks, commissions, margin),
     - closed trades,
     - equity curve.
   - All writes happen in one transaction per fill/close.
3. **Hydration**
   - `PaperTradingEngine` gets a repository or a hydrate/snapshot API.
   - API, worker, and runner use the same repository implementation.
   - Remove the “two independent singletons” behavior.
4. **Worker**
   - On close, write `positions`, `trade_history`, `orders`, and `portfolio` atomically.
   - Do not rely on a projection-only sync.
5. **Tests**
   - Real Postgres integration test:
     - open long,
     - open short,
     - restart/rebuild,
     - compare engine snapshot to DB,
     - check promotion counts and drawdown.
   - Add a regression test that every column referenced by worker/agent SQL exists in the schema.

**Do not** start by rewriting all agents. Keep the interface surgical and preserve existing tests.

### P1-B — Secure `/execute`

- Decide whether `/execute` is:
  - an internal execution endpoint that requires an approved signal/risk payload, or
  - a manual paper-trade endpoint.
- Preferred: require an approved signal/risk contract; reject otherwise.
- Add idempotency (`client_order_id` or equivalent) and a duplicate-order test.
- If manual, mark the trade as manual and exclude it from promotion metrics, or explicitly document why it counts.
- Add a test that `/execute` without approval cannot create a position.

### P1-C — Schema, migrations, CI

- Track `migrations/versions/`.
- Collapse the two Alembic heads.
- Pick one schema source; delete or generate the duplicate.
- Add a Postgres-backed test job (testcontainers or Compose service).
- Fix the 22 mypy errors.
- Add CI steps:
  - `pytest`
  - `ruff check`
  - `ruff format --check`
  - `mypy`
  - frontend build
  - frontend lint (after fixing the script)

### P1-D — Authorization and kill-switch operations

- Add roles to `users`/JWT/API-key mapping.
- Require operator/admin for:
  - `/live/start`
  - `/live/kill`
  - `/live/arm`
  - mode changes
  - live config changes
- Add route tests for viewer/operator/admin.
- Add a shared Redis arm epoch so one human re-arm clears all processes.

### P2-A — Paper realism

- Pass candle open into `check_sl_tp`; if the market gaps through the stop, fill at the worse of open/stop.
- Add per-symbol/asset commission and slippage.
- Add short borrow/funding costs.
- Model partial fills/liquidity for larger orders.
- Persist and expose the equity curve.

### P2-B — Frontend and UX

- Replace `Math.random()` market candles with a real endpoint.
- Make analysis explicit rather than auto-running on mount.
- Persist settings through the API; remove fake secret previews and fake values.
- Add request timeouts/abort and typed errors.
- Fix `pnpm lint`; add accessibility checks.
- Show fees/margin/equity consistently across portfolio/paper/live pages.

### P2-C — Analysis isolation and observability

- Replace global `_last_state` with per-run state.
- Add a bounded queue/semaphore and cancellation.
- Emit Prometheus metrics for:
  - rejected signals,
  - paper fills,
  - agent/model failures/fallbacks,
  - worker errors,
  - kill-switch state.
- Add alerts for drawdown and stale workers.
- Add a real model-catalog CI check.

---

## 9. Exact verification commands

Run from repository root unless noted.

```powershell
# Full suite
python -m pytest tests/ -q

# Focused paper/execution tests
python -m pytest tests/test_paper_trading.py tests/test_paper_trading_worker.py `
  tests/test_execution_agent.py tests/test_consensus.py tests/test_config.py -q --no-cov

# Lint/format
ruff check .
ruff format --check .

# Type checks (expected 22 test/script errors today)
mypy .

# Frontend
cd frontend
pnpm build
cd ..

# Compose overlay validation (use dummy values; keep output quiet)
$env:API_SECRET_KEY='test-only-key'
$env:POSTGRES_PASSWORD='test-only-db'
$env:JWT_SECRET_KEY='test-only-jwt'
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet

# Docker-stack variant
cd docker
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
cd ..
```

Do not run the Compose command without dummy values if there is any chance the resolved output will be captured; `.env` may contain live keys.

---

## 10. Traps and gotchas found during review

1. **`unrealized_pnl` contains the substring `realized_pnl`.** A naive test for missing `realized_pnl` fails. Use a word-boundary regex if guarding SQL.
2. **Mocked sessions do not validate SQL columns.** The worker had three real schema errors while all tests passed. Add real DB integration tests.
3. **`positions` has no `side`, no `realized_pnl`.** Do not add either to SQL without a migration.
4. **`orders` has no `strategy_name` / `reason`.** Use `agent_rationale` JSONB or add columns through a migration.
5. **`paper_trades` is unused.** Promotion reads `trade_history`; do not “fix” promotion by writing `paper_trades` without checking `live_trading/engine.py`.
6. **The engine constructor is intentionally frictionless by default.** If you make fees default non-zero, many unit tests and direct callers change behavior.
7. **The API and runner are separate processes.** A module-level singleton is per process, not shared.
8. **The worker only syncs the portfolio on closure.** Entry/reversal and a restart still leave DB and engine divergent.
9. **The stop-first policy is deliberate.** Do not revert to TP-first; it inflates paper results.
10. **Consensus exactly 80% is rejected.** Do not change back to `>=` to make an old test pass.
11. **Production overlay uses map-style environment merging.** Keep it aligned with root Compose service names (`backend`, `run-live`, `daily-reporter`).
12. **Do not commit `.env` or print resolved Compose output.**
13. **`pnpm lint` is currently broken by the Next 16 migration.** It is not evidence that the frontend code is broken; `pnpm build` passes.

---

## 11. Definition of done for the next session

A change is not finished until:

- the focused tests pass first,
- `pytest tests/ -q` passes,
- coverage stays at or above 78%,
- `ruff check .` and `ruff format --check .` are clean,
- `mypy` has no new errors (ideally all 22 are fixed if you are claiming CI green),
- frontend `pnpm build` passes for frontend changes,
- docs and the routed `CONTEXT.md` are updated,
- `docs/02-STATUS.md` is updated with verified numbers, not estimates,
- no safety gate was weakened,
- no secrets are added to tracked files,
- no commit/push is made unless the user explicitly asks.

---

## 12. Handoff summary in one paragraph

The P0 phase is complete: auth, kill switch, one live path, free-model fallback, realistic paper accounting, production secret enforcement, and strict consensus thresholds are in place and verified at 1044 tests / 79.08% coverage. The platform is still paper-only and the live code remains gated. The highest-value next change is a durable, single-source paper ledger with `positions.side`, restart hydration, atomic DB writes, and Postgres integration tests. After that, secure the direct `/execute` endpoint, fix schema/migration drift and the 22 mypy errors, add role-based live authorization and a shared kill-switch arm epoch, and only then move to paper realism and frontend/observability work. The working tree is intentionally uncommitted; do not reset or commit without explicit user approval.
