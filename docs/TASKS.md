<!-- docs/TASKS.md — current work queue; canonical plan is 05-NEXT.md -->
# Tasks — current queue

> This is a working checklist derived from `docs/05-NEXT.md`. The canonical plan
> and acceptance criteria live there; `docs/02-STATUS.md` records verified state.
> Do not start a later phase before the previous exit criterion unless a human
> explicitly reprioritizes.
>
> Last checked: 2026-10-28 against `master` (`096c575`).

## Now — Phase 2 (product realism and UI)

- [x] `markets/page.tsx`: replace `Math.random()` candles with real candle data.
      (2026-10-22: `GET /api/v1/market/candles`, Binance for crypto, Yahoo for equities.)
- [x] `markets/page.tsx`: remove auto-analysis on mount/symbol change; make it an
      explicit action. (2026-10-22)
- [x] `markets/page.tsx`: dispose the chart on unmount (`chart.remove()`). (2026-10-22)
- [x] `markets/page.tsx`: guard concurrent analysis runs. (2026-10-22)
- [x] Label the markets symbol select and announce analysis state with `aria-live`.
      (2026-10-22)
- [x] Settings backend: authenticated `GET /api/v1/settings` and
      `PUT /api/v1/settings/preferences`; singleton `app_settings` table and
      migration `0005`; safety limits read-only. (2026-10-22)
- [x] `settings/page.tsx`: persist settings through the API; remove the
      `setTimeout` save. (2026-10-22)
- [x] `settings/page.tsx`: fix `localhost:8080` vs the client `8000`.
      (2026-10-22: API URL comes from `NEXT_PUBLIC_API_URL`.)
- [x] `settings/page.tsx`: align `max_position_size` 10% with backend 2%.
      (2026-10-22: read-only `MAX_POSITION_SIZE_PCT`.)
- [x] `settings/page.tsx`: remove the fake secret preview. (2026-10-22)
- [x] `live/page.tsx`: fetch status and audit with `Promise.all`. (2026-10-22)
- [x] `live/page.tsx`: pause polling when the tab is hidden; add an in-flight guard.
      (2026-10-22: interval comes from `live_refresh_seconds`; controls force refresh.)
- [x] `usePipelinePolling.ts`: one poll at a time, abort on unmount, backoff on
      errors. (2026-10-22)
- [x] `api.ts`: request timeout/abort and typed errors. (2026-10-22)
- [x] Accessibility: skip link, `aria-current`, labelled live controls, dialog ARIA,
      strategy-builder labels/`aria-pressed`, and stronger small-text contrast.
      (2026-10-22; axe/Lighthouse pass 2026-10-24)
- [x] Strategy builder: persist drafts through `/api/v1/strategies`; keep status,
      live enablement, and promotion fields server-owned. (2026-10-22)
- [x] Chat: real multi-turn, read-only workflow through `POST /api/v1/chat`;
      free-tier fallback chain, bounded history, no tools or trade path.
      (2026-10-22; streaming and conversation persistence remain future work)
- [x] Frontend lint/typecheck/test job in CI. (2026-10-22)

**Phase 2 exit:** no page renders invented data; settings round-trip through the
API; chat is multi-turn and read-only; axe/Lighthouse pass (met 2026-10-24).

## Next — P1 gaps

- [x] `/analyze` concurrency/cost control: replace the module-global
      `_last_state`, bound concurrent runs, add timeouts/cancellation and a cost
      budget. (2026-10-28: `backend/services/analysis_control.py` adds a bounded
      per-session store, a process-wide semaphore (default one run), a rolling
      hourly run budget, `ANALYSIS_TIMEOUT_SECONDS` as a stage-start deadline
      that is cleared before execution, and cancellation handling;
      `/analyze` and `/analyze/stream` return **429** when busy or over budget,
      `/signal` returns **504** when the deadline fires before execution, and
      `/agents/status?session_id=` reads a specific run.
      `tests/test_analysis_control.py`, `tests/test_analysis_router.py`, and
      `tests/test_supervisor.py` cover the limits and terminal paths.)
- [x] Shared Redis kill-switch arm epoch so one human re-arm clears the API and
      every runner. (2026-10-28: `KillSwitch.arm()` atomically clears the active
      state and publishes an `arm:` token at `ares:kill_switch:arm_epoch`; each
      process clears its latch only on an `arm:` token different from its observed
      baseline. A missing/flushed token, a republished `baseline:`, or store
      recovery alone never clears it. A process that latched before its first
      read needs one further arm. Covered by
      `tests/test_live_trading/test_safety_edge_cases.py`; see ADR-024.)
- [ ] Manually reconcile pre-P1-A short positions that were migrated as long.
      (Operational: `02-STATUS.md` gap #10 records that old shorts cannot be
      inferred and default to long. Needs a human with production DB access.)

## Next — P2 gaps

- [ ] Bind `/execute` to a signed/expiring approval or a stored `signals` row;
      do not rely only on caller-supplied agent payloads. (Verified 2026-10-28:
      `ExecuteTradeRequest` still carries `TradeApproval`; no `signal_id` or
      signed/expiring token.)
- [x] Remove remaining frontend mock data from markets, settings, and the strategy
      builder. (2026-10-22)
- [x] Fix frontend lint under Next 16 and add the frontend lint/typecheck/test CI job.
      (2026-10-22; ESLint 9 + `tsc --noEmit` + Vitest, 18 tests now)
- [x] CI validates the roster's free-only policy. (2026-10-26: #115 adds
      `tests/test_client.py::TestFreeOnlyModelRoster`, which runs in the `test` job.)
- [ ] Scheduled live-catalog validation of the model roster so removals are
      caught. (Verified 2026-10-28: `scripts/test_free_models.py` exists and is
      documented, but `ci.yml` has no `schedule:` trigger and does not run it.)
- [ ] Paper realism: gap-through stop fills, partial fills/liquidity,
      borrow/funding costs, per-symbol slippage. (Verified 2026-10-28: commission
      plus one global `paper_trading_slippage_pct` only; see
      `paper_trading/CONTEXT.md` Known gaps.)
- [ ] Close the paid-model bypass in `agents/web_collector.py`. Its optional
      `browser_use` path builds `ChatOpenAI` with `openai/gpt-4o-mini` or
      `gemini/gemini-2.0-flash`, bypassing the `LLMClient` free-only guard.
      (Found 2026-10-28; directly reachable from `/predictions` when the optional
      dependency and a paid key are present. It is registered in the analysis
      registry but is not a `PIPELINE_ORDER` node.)

## Later — Phase 3 hygiene

- [x] Keep `mypy .` green. (Verified 2026-10-28: clean on 211 files; enforced
      by the `lint` CI job via `uv run mypy .`.)
- [x] Re-verify README numbers and roadmap status. (2026-10-24: README no longer
      carries counts; it points at `02-STATUS.md`. `05-NEXT.md` refreshed.)
- [x] Improvement engine: rename “win rate” to execution rate and remove the
      75% consensus suggestion. (2026-10-24)
- [x] Improvement engine: persist reflection/improvement history across restarts
      and invoke analysis after the reflection node. (2026-10-24: migration `0006`,
      `improvement_service`, best-effort supervisor hook in `/analyze` and the live
      runner; backtests intentionally do not record history.)
- [ ] Link improvement suggestions to the exact config field they would change.
      (`05-NEXT.md` Phase 3 remaining; suggestions are not yet actionable.)
- [x] Add Prometheus alert rules; remove duplicate monitoring configs. (2026-10-24:
      7 rules in `docker/monitoring/alert-rules.yml`, `promtool` clean; both compose
      files mount the tracked set.)
- [ ] Add an Alertmanager target so the 7 alert rules page. (`05-NEXT.md` Phase 3
      remaining; rules evaluate but nothing delivers them today.)
- [x] Land the Dependabot queue. (2026-10-25: merged green #57, #56, #67.
      2026-10-26: #114 consolidated 14 more bumps; #116 ported
      `lightweight-charts` v5 and closed #82.)
- [ ] Prune merged remote branches left by #114/#115/#116. (Nine older merged
      branches were deleted 2026-10-25; these three remain. Deletion needs
      explicit approval.)

## Documentation

- [x] ICM entry catalog and per-folder `CONTEXT.md` files.
- [x] Conventional docs set (PRD, API, DB, setup, deployment, security, testing,
      debugging, tasks, roadmap, decisions, conventions, integrations, MCP).
- [x] Re-run link checks after any doc move. (Automated 2026-10-28:
      `tests/test_icm_structure.py::test_relative_links_resolve` checks relative
      links in entry docs and runs in the `test` job; 20 passed.)

## Guardrails

- Paper-only by default; live trading is opt-in and gated.
- Never weaken the kill switch, human approval, promotion gate, or a test.
- Model IDs only in `configs/models.yaml`; secrets only in `.env`.
- Update `docs/02-STATUS.md` and the routed `CONTEXT.md` in the same change.
- Ask before commit/push or any external side effect.

## Read next

- Full plan and acceptance criteria: `docs/05-NEXT.md`
- Feature status: `docs/FEATURES.md`
- Verified state: `docs/02-STATUS.md`
