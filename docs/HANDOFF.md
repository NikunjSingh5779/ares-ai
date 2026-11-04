<!-- docs/HANDOFF.md -->
# Session handoff — 2026-11-04

**Read this first in a new session.** It is a snapshot for continuity, not a second
status file. `docs/02-STATUS.md` remains the verified source of truth; if this file and
the code disagree, the code wins.

## Where the repo is

| Item | Value |
|---|---|
| Root | `C:\Users\ASUS\ares-ai` (Windows, PowerShell) |
| Branch | `master` at `7b9761f` (`docs: record the catalog workflow's first run`) |
| Working tree | **Dirty** — paper-realism slice 2 (borrow/funding carry) is implemented but uncommitted, plus this handoff; run `git status` for the exact list |
| Alembic head | `0007_carry_costs` |
| Last merged slice | PR #135, squash-merged as `779f2ad` (gap-through stops + per-symbol slippage) |

The uncommitted slice touches: `paper_trading/{engine,repository,ledger,worker}.py`,
`configs/settings.py`, `backend/routers/trading.py`, `frontend/src/types/api.ts`,
`database/{schema,init}.sql`, migration `0007`, `.env.example`, tests, and docs
(`02-STATUS`, `05-NEXT`, `03-ARCHITECTURE`, `04-DECISIONS`, `DATABASE`, `DECISIONS`,
`DEBUGGING`, `DEPLOYMENT`, `FEATURES`, `IMPLEMENTATION`, `ROADMAP`, `TASKS`, `API`,
`PRD`, `TESTING`, the `paper_trading`/`database` contracts, two map cards, and this
handoff).

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

**Not yet run:** the new real-PostgreSQL carry round-trip in
`tests/test_postgres_integration.py`. It is written and will run in CI's
`postgres-integration` job (the local default suite skips it without
`ARES_TEST_POSTGRES_URL`). Do not claim it passed until CI or a local disposable
PostgreSQL run says so.

## What to do next, in order

1. **Review the uncommitted diff** for accounting and safety correctness. Do not weaken
   safety gates, kill switches, approvals, promotion gates, drawdown/exposure checks, or
   test assertions.
2. **Commit and open a PR for the carry slice.** Create a feature branch (for example
   `feat/paper-carry-costs`), commit with a focused message, push, and open a PR.
   **Push and PR creation require explicit user approval.** Watch all five CI jobs;
   confirm `postgres-integration` runs the new carry case.
3. **After merge:** update `docs/02-STATUS.md` with the merge commit, CI run IDs, and
   remove the "uncommitted" wording; update `docs/05-NEXT.md` if priorities shift.
4. **Next paper-realism slice: partial fills/liquidity.** Design it before coding:
   order status, volume-limited fills, partial closes, and persistence changes. It is
   the only remaining item in the paper-realism sequence.
5. **Operational gaps (need credentials/production access, not code):**
   - Add the `OPENROUTER_API_KEY` repository secret and run the model-catalog workflow
     via `workflow_dispatch` (gap #9; the first scheduled run failed closed at the guard).
   - Reconcile pre-P1-A short positions that migrated as long (gap #10; needs production
     database access).
6. **Optional P2/P3:** local chat is chat-only/process-gated (gap #14); the accessibility
   audit did not exercise data-populated states (gap #16).

## Key files

| Area | Files |
|---|---|
| Carry engine | `paper_trading/engine.py` — `PaperPosition.carry_cost`/`last_accrual_at`, `ClosedTrade.carry_cost`, `PortfolioSummary.carry_cost`, `accrue_carry`, `mark_to_market(as_of)`, `check_sl_tp(as_of)`, `close_position(exit_at)`, `_accrue_position` |
| Persistence | `paper_trading/repository.py` — hydrate/upsert/close/trade-history SQL |
| Service wiring | `paper_trading/ledger.py` (`process_candle(as_of)`), `paper_trading/worker.py`, `scripts/run_live.py` |
| Settings | `configs/settings.py` — four carry fields and per-symbol validators |
| API | `backend/routers/trading.py` — factory wiring and response dicts |
| Schema | `database/schema.sql`, `database/init.sql` (must stay byte-identical), `migrations/versions/0007_carry_costs.py` |
| Tests | `tests/test_paper_trading.py`, `tests/test_paper_trading_ledger.py`, `tests/test_paper_trading_worker.py`, `tests/test_config.py`, `tests/test_trading_router.py`, `tests/test_schema.py`, `tests/test_postgres_integration.py` |
| Contracts/map | `paper_trading/CONTEXT.md`, `database/CONTEXT.md`, `docs/map/objects/portfolio.md`, `docs/map/processes/execution.md` |
| Status/plan | `docs/02-STATUS.md`, `docs/05-NEXT.md`, `docs/04-DECISIONS.md` (ADR-026), `docs/TASKS.md` |

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
4. docs/HANDOFF.md — this handoff, including the exact uncommitted slice.
5. The CONTEXT.md for the folder you are about to edit.

Current state (2026-11-04):
- master is at 7b9761f.
- The working tree contains the UNCOMMITTED paper-realism slice 2 (borrow/funding carry):
  engine accrual/settlement, repository SQL, schema + migration 0007, settings, API
  fields, frontend types, tests, and docs.
- Verified locally: pytest tests/ -q -> 1434 passed, 3 skipped, 84.44%; ruff check . and
  ruff format --check . clean; mypy . clean on 216 files; ICM+infra 44 passed;
  alembic heads -> 0007_carry_costs.
- Not committed, pushed, or CI-tested. The new PostgreSQL carry round-trip will run in
  CI's postgres-integration job on the PR.

Your first task:
1. Review the uncommitted diff for accounting and safety correctness. Do not weaken
   safety gates, kill switches, approvals, promotion gates, drawdown/exposure checks, or
   test assertions.
2. Create a feature branch (for example feat/paper-carry-costs), commit with a focused
   message, and open a PR. Do NOT push or open the PR until I explicitly approve it.
3. Watch all five CI jobs; confirm postgres-integration runs the new carry test. Fix any
   failures without weakening a gate.
4. After merge, update docs/02-STATUS.md with the merge commit and CI run IDs, remove the
   "uncommitted" wording, and update docs/05-NEXT.md if priorities shift.

Constraints:
- Paper-only. Never weaken a safety gate to make a test pass.
- Free-tier/local models only. Never read, print, or commit secrets.
- Push, remote branch deletion, PR merge/close, dependency installs, and credential use
  require explicit approval.
- Definition of done: tests pass, ruff + mypy clean, docs updated in the same change.
- Update docs/02-STATUS.md when state changes.

After the carry PR is merged, the next paper-realism slice is partial fills/liquidity.
Do not start it until the carry PR is merged and I agree.
```
