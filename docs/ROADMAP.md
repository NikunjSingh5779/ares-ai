<!-- docs/ROADMAP.md — conventional roadmap summary; history is milestone-roadmap.md -->
# Roadmap — ARES AI

> `docs/milestone-roadmap.md` is the milestone history. `docs/05-NEXT.md` is the
> ordered, testable plan. `docs/02-STATUS.md` is the verified current state.
> This file is the short view.

## Where we are

- **Phase 0 — capital safety:** closed on 2026-10-21.
- **Phase 1 — one source of truth:** closed on 2026-10-21. Durable paper
  ledger, approved `/execute`, idempotency, writer lock, real-PostgreSQL CI,
  degraded health, Prometheus metrics, role authorization, and the Compose
  restart exit are complete.
- **Phase 2 — product realism and UI:** closed on 2026-10-24. Real candles,
  persisted settings, strategy drafts, bounded polling, read-only chat, frontend CI,
  and the accessibility audit are complete.
- **Phase 3 — hygiene:** in progress. Typing, README numbers, and improvement history
  are done; Prometheus alert rules and branch/Dependabot cleanup remain.

## Milestone history (verified)

| Milestone | Status |
|---|---|
| M1 Infrastructure foundation | Verified |
| M2 Data layer and market ingestion | Verified |
| M3 Agent framework and supervisor | Verified |
| M4 Market Analyst and News | Verified |
| M5 Quant and Vision | Verified |
| M6 Consensus and Risk | Verified |
| M7 Execution, Journal, paper trading | Verified |
| M8 Memory and Reflection | Verified |
| M9 Backtest engine | Verified; custom simulator, library choice open |
| M10 API gateway | Verified |
| M11 Frontend dashboard | Verified; Phase 2 exit met 2026-10-24 |
| M12 Live trading and safety gates | Verified; Zerodha/IBKR order methods are stubs |
| M13 Monitoring, CI/CD, security | Verified |
| S1 Login brute-force protection | Verified |
| R1 Deterministic frontend dependencies | Verified |

## Phase 2 exit criteria

- Real market candles and explicit analysis triggers.
- Settings round-trip through the API with correct values.
- No fabricated data in any page.
- Polling is guarded, abortable, and backs off on errors.
- Accessibility checks pass. (met 2026-10-24: Lighthouse 100 on `/login`, 0 axe
  violations across 16 authenticated route shells)
- Frontend lint/typecheck/test runs in CI. (met 2026-10-22)

## Phase 3 exit criteria

- Mypy stays green.
- README and roadmap numbers match verified state.
- Improvement history is persisted and naming is consistent. (met 2026-10-24:
  `reflection_runs`/`improvement_records`, migration `0006`, post-run hook)
- Prometheus alert rules exist without duplicate configs.
- Stale branches and Dependabot PRs are handled.

## Open product decisions

- Keep the custom pure-Python backtest engine or adopt VectorBT/Backtrader.
- Signed/stored approval for `/execute` versus the current API-key trust
  boundary.
- Shared kill-switch arm epoch design for multiple runners.
- Paper realism depth: gap-through stops, partial fills, funding/borrow costs.

## Read next

- Ordered work and acceptance criteria: `docs/05-NEXT.md`
- Task checklist: `docs/TASKS.md`
- Milestone history: `docs/milestone-roadmap.md`
- Decisions: `docs/04-DECISIONS.md`
