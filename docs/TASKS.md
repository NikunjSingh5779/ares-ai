<!-- docs/TASKS.md — current work queue; canonical plan is 05-NEXT.md -->
# Tasks — current queue

> This is a working checklist derived from `docs/05-NEXT.md`. The canonical plan
> and acceptance criteria live there; `docs/02-STATUS.md` records verified state.
> Do not start a later phase before the previous exit criterion unless a human
> explicitly reprioritizes.

## Now — Phase 2 (product realism and UI)

- [ ] `markets/page.tsx`: replace `Math.random()` candles with real candle data.
- [ ] `markets/page.tsx`: remove auto-analysis on mount/symbol change; make it an
      explicit action.
- [ ] `markets/page.tsx`: dispose the chart on unmount (`chart.remove()`).
- [ ] `markets/page.tsx`: guard concurrent analysis runs.
- [ ] `settings/page.tsx`: persist settings through the API; remove the
      `setTimeout` save.
- [ ] `settings/page.tsx`: fix `localhost:8080` vs the client `8000`.
- [ ] `settings/page.tsx`: align `max_position_size` 10% with backend 2%.
- [ ] `settings/page.tsx`: remove the fake secret preview.
- [ ] `live/page.tsx`: fetch status and audit with `Promise.all`.
- [ ] `live/page.tsx`: pause polling when the tab is hidden; add an in-flight guard.
- [ ] `usePipelinePolling.ts`: one poll at a time, abort on unmount, backoff on
      errors.
- [ ] `api.ts`: request timeout/abort and typed errors.
- [ ] Accessibility: label the symbol select, connect settings labels with
      `htmlFor`, `role="switch"`/`aria-checked`, `aria-live` for run/error state,
      skip link, stronger small-text contrast.
- [ ] Functional strategy builder and real chat interface.
- [ ] Frontend lint/typecheck/test job in CI.

**Phase 2 exit:** no page renders invented data; settings round-trip through the
API; axe/Lighthouse pass.

## Next — P1 gaps

- [ ] `/analyze` concurrency/cost control: replace the module-global
      `_last_state`, bound concurrent runs, add timeouts/cancellation and a cost
      budget.
- [ ] Shared Redis kill-switch arm epoch so one human re-arm clears the API and
      every runner.
- [ ] Manually reconcile pre-P1-A short positions that were migrated as long.

## Next — P2 gaps

- [ ] Bind `/execute` to a signed/expiring approval or a stored `signals` row;
      do not rely only on caller-supplied agent payloads.
- [ ] Remove remaining frontend mock data; fix frontend lint under Next 16.
- [ ] Add scheduled/CI validation of the model catalog.
- [ ] Paper realism: gap-through stop fills, partial fills/liquidity,
      borrow/funding costs, per-symbol slippage.

## Later — Phase 3 hygiene

- [ ] Keep `mypy .` green.
- [ ] Re-verify README numbers and roadmap status.
- [ ] Improvement engine: persist history, rename “win rate”, remove the 75%
      consensus suggestion.
- [ ] Add Prometheus alert rules; remove duplicate monitoring configs.
- [ ] Prune stale branches and land Dependabot PRs.

## Documentation

- [x] ICM entry catalog and per-folder `CONTEXT.md` files.
- [x] Conventional docs set (PRD, API, DB, setup, deployment, security, testing,
      debugging, tasks, roadmap, decisions, conventions, integrations, MCP).
- [ ] Re-run link checks after any doc move.

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
