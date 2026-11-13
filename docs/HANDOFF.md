<!-- docs/HANDOFF.md -->
# Session handoff — 2026-11-04

**Read this first in a new session.** It is a snapshot for continuity, not a second
status file. `docs/02-STATUS.md` remains the verified source of truth; if this file and
the code disagree, the code wins.

## Where the repo is

| Item | Value |
|---|---|
| Root | `C:\Users\ASUS\ares-ai` (Windows, PowerShell) |
| Branch | `master` at `b49223a` (`feat(paper): accrue and settle borrow/funding carry (#136)`) |
| Working tree | **Clean** — slice 2 is merged; only this post-merge docs bookkeeping may be pending |
| Alembic head | `0007_carry_costs` |
| Last merged slice | PR #136, squash-merged as `b49223a` (paper-realism slice 2: borrow/funding carry) |
| Prior merged slice | PR #135, squash-merged as `779f2ad` (gap-through stops + per-symbol slippage) |

Slice 2 landed across `paper_trading/{engine,repository,ledger,worker}.py`,
`configs/settings.py`, `backend/routers/trading.py`, `frontend/src/types/api.ts`,
`database/{schema,init}.sql`, migration `0007`, `.env.example`, tests, and docs.

## What was just built (do not redo)

Paper realism slice 2 adds borrow/funding **carry** to paper trading:

- **Rates:** annualized decimals. `PAPER_TRADING_BORROW_RATE_PCT` defaults to `0.10`
  (10%/year, charged on short notional); `PAPER_TRADING_FUNDING_RATE_PCT` defaults to
  `0.0` (charged on long notional). Per-symbol JSON maps
  (`PAPER_TRADING_BORROW_RATE_BY_SYMBOL`, `PAPER_TRADING_FUNDING_RATE_BY_SYMBOL`)
  override the global rate. Rates are non-negative and bounded `< 10.0`. There are no
  funding credits.
- **Accrual:** `entry_notional × annual_rate × elapsed_seconds / (365 days)`, measured
  from `last_accrual_at`. A timestamp at or before the stored clock is ignored; a zero
  rate still advances the clock. `process_candle`/`mark_to_market` accrue to the candle
  timestamp; `close_position` accrues the final partial period before settling.
- **Accounting:** open carry is an equity liability (subtracted from equity). At close it
  is deducted from cash and from the trade's PnL. `PortfolioSummary.carry_cost` reports
  open plus closed carry.
- **Persistence:** `positions.carry_cost`, `positions.last_accrual_at`,
  `trade_history.carry_cost`. Migration `0007` adds them idempotently and backfills
  `last_accrual_at` from `opened_at`. The repository hydrates, upserts, closes, and writes
  history with all three.
- **API/UI:** `/portfolio` exposes `carry_cost`; `/positions` exposes `carry_cost` and
  `last_accrual_at`; `/orders` exposes `carry_cost`. Frontend fields are optional.
- **Wiring:** `get_paper_trading_ledger()` passes all four settings to the shared engine;
  the worker and `scripts/run_live.py` pass `candle.timestamp` into `process_candle`.

## Verification already run (2026-11-04)

| Check | Result |
|---|---|
| `uv run pytest tests/ -q` | **1434 passed, 3 skipped**, 84.44% coverage |
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | 273 files already formatted |
| `uv run mypy .` | clean, 216 source files |
| `uv run pytest tests/test_icm_structure.py tests/test_infra_config.py -q --no-cov` | **44 passed** |
| `uv run alembic heads` | `0007_carry_costs (head)` |
| Targeted slice run | **199 passed** across paper/config/router/schema modules |
| Local PostgreSQL suite | **24 passed** (6 ledger, 12 strategy, 6 improvement) on a disposable PostgreSQL 16 container |

## What to do next, in order

1. **Nothing is pending on slice 2.** PR #136 is merged as `b49223a`, the remote
   `feat/paper-carry-costs` branch is deleted, and the merge was verified by runs
   **41856026984** (branch push), **41856038721** (PR), and **41856711393**
   (post-merge master). All five jobs were green in each; `postgres-integration`
   reported **24 passed**, including
   `test_carry_survives_restart_and_settles_on_close`. Do not re-review or re-merge it.
2. **Paper-realism slice 3 (partial fills/liquidity) is merged** as `854428c` via PR
   #144 (ADR-027): IOC market orders with a volume-participation cap, volume-limited
   stop/TP exits, partial closes with proportional commission/carry allocation, and
   partial-aware persistence with no schema change. Branch/PR/post-merge runs
   **43445079894**, **43445130807**, and **43446142786** were all green
   (`postgres-integration` 25 passed, including the partial-fill round-trip). Do not
   re-review or re-merge it. The remote `feat/paper-partial-fills` branch still needs
   deletion after approval.
3. **Operational gaps (need credentials/production access, not code):**
   - Add the `OPENROUTER_API_KEY` repository secret and run the model-catalog workflow
     via `workflow_dispatch` (gap #9; the first scheduled run failed closed at the guard).
   - Reconcile pre-P1-A short positions that migrated as long (gap #10; needs production
     database access).
4. Nothing else is queued in code; a further paper-realism slice (for example
   price-impact modelling) needs explicit human agreement first.

## Key files

| Area | Files |
|---|---|
| Carry engine | `paper_trading/engine.py` — `PaperPosition.carry_cost`/`last_accrual_at`, `ClosedTrade.carry_cost`, `PortfolioSummary.carry_cost`, `accrue_carry`, `mark_to_market(as_of)`, `check_sl_tp(as_of, volume)`, `close_position(exit_at, quantity)`, `_accrue_position`, `_liquidity_capacity` |
| Partial fills | `paper_trading/engine.py` — `execute_signal(volume=)` IOC result keys, `max_volume_participation_pct`, `PaperPosition.requested_quantity`/`entry_order_status`/`entry_order_reason`, `QUANTITY_EPSILON` |
| Persistence | `paper_trading/repository.py` — hydrate/upsert/close/trade-history SQL; entry orders write `status`/`filled_quantity`/`failure_reason`; partial exits upsert instead of closing |
| Service wiring | `paper_trading/ledger.py` (`process_candle(as_of, volume)`), `paper_trading/worker.py`, `scripts/run_live.py`, `agents/execution.py` (candle volume + partial-fill rationale), `agents/market_analyst.py` (`current_volume` indicator) |
| Settings | `configs/settings.py` — carry fields, per-symbol validators, `paper_trading_max_volume_participation_pct`; `.env.example` mirrors them |
| API | `backend/routers/trading.py` — factory wiring, `current_volume` extraction, response dicts |
| Schema | `database/schema.sql`, `database/init.sql` (must stay byte-identical; no slice-3 change), `migrations/versions/0007_carry_costs.py` |
| Tests | `tests/test_paper_trading.py`, `tests/test_paper_trading_ledger.py`, `tests/test_paper_trading_worker.py`, `tests/test_config.py`, `tests/test_trading_router.py`, `tests/test_schema.py`, `tests/test_postgres_integration.py` |
| Contracts/map | `paper_trading/CONTEXT.md`, `database/CONTEXT.md`, `docs/map/objects/portfolio.md`, `docs/map/processes/execution.md` |
| Status/plan | `docs/02-STATUS.md`, `docs/05-NEXT.md`, `docs/04-DECISIONS.md` (ADR-026, ADR-027), `docs/TASKS.md` |

## Commands

```powershell
uv sync --locked --all-extras --dev
uv run pytest tests/ -q
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest tests/test_icm_structure.py tests/test_infra_config.py -q --no-cov
uv run alembic heads
```

For the real-PostgreSQL module, set `ARES_TEST_POSTGRES_URL` to a disposable database
whose name contains `test`; the module has a safety guard against real ledgers.

## Hard rules (do not drift)

1. Free-tier models only; model IDs live in `configs/models.yaml`, never in agent source.
2. Every agent input/output is a typed Pydantic schema; `rationale` is required wherever
   a trading number is produced.
3. **No signal = no trade.** A required agent that fails rejects the trade.
4. Market Analyst and Quant must both exceed 80% confidence, Risk must approve, and
   drawdown/exposure must be safe.
5. Live trading starts in human-approval mode; autonomous mode is opt-in per strategy
   only after the paper-trading promotion gate.
6. A kill switch must halt order placement and require human re-arm. Never bypass a
   safety gate.
7. Never hardcode secrets or commit `.env`. `.env.example` only.
8. Model failure degrades gracefully and is logged with the fallback used.
9. Definition of done: tests pass, `ruff` + `mypy` clean, docs updated in the same change.
10. Never weaken a safety gate to make a test pass.

## Paste-ready prompt for a new session

Copy everything inside the fenced block:

```text
You are continuing work on the ARES AI repo at C:\Users\ASUS\ares-ai (Windows, PowerShell).

Read these before touching anything, in this order:
1. AGENTS.md (repo root) — entry catalog and hard rules.
2. docs/02-STATUS.md — verified state and known gaps.
3. docs/05-NEXT.md — priorities; start with "Immediate next move".
4. docs/HANDOFF.md — this handoff, including the merged slice and next move.
5. The CONTEXT.md for the folder you are about to edit.

Current state (2026-11-04):
- master is at b49223a. Paper-realism slice 2 (borrow/funding carry) is MERGED as
  PR #136 (b49223a); its remote branch is deleted.
- All five CI jobs passed on the branch push (41856026984), the PR (41856038721), and
  the post-merge master push (41856711393). postgres-integration ran 24 tests,
  including test_carry_survives_restart_and_settles_on_close.
- Verified locally before merge: pytest tests/ -q -> 1434 passed, 3 skipped, 84.44%;
  ruff check . and ruff format --check . clean; mypy . clean on 216 files; ICM+infra
  44 passed; alembic heads -> 0007_carry_costs; local PostgreSQL suite 24 passed.

Your first task:
1. Read the docs above and confirm the working tree is clean (git status).
2. Do not redo slices 1–3 or their review; all three are merged (slice 3 as `854428c`
   via PR #144). The remote `feat/paper-partial-fills` branch deletion is the only
   pending branch cleanup and needs approval.
3. Nothing else is queued in code; the remaining items are operational gaps #9 and
   #10, which need credentials or production database access.

Constraints:
- Paper-only. Never weaken a safety gate to make a test pass.
- Free-tier/local models only. Never read, print, or commit secrets.
- Push, remote branch deletion, PR merge/close, dependency installs, and credential use
  require explicit approval.
- Definition of done: tests pass, ruff + mypy clean, docs updated in the same change.
- Update docs/02-STATUS.md when state changes.

Do not start any further paper-realism work without my agreement.
```
