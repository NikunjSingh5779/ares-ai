<!-- docs/milestone-roadmap.md -->
# ARES AI — Milestone Roadmap

**Last verified against actual code + passing tests: 2026-07-25.** Every row below was
checked by reading the implementation and/or running its tests — not inferred from a
prior status label. See "Reconciliation note" if a git branch name uses a different
milestone number than this table.

| # | Milestone | Status |
|---|-----------|--------|
| M1 | Infrastructure Foundation — Docker, DB schema, configs, agent base, CI/CD | ✅ Verified |
| M2 | Data Layer + Market Data Ingestion | ✅ Verified (not independently deep-audited this pass) |
| M3 | Agent Framework + Supervisor (LangGraph) | ✅ Verified — `PIPELINE_ORDER` in `agents/supervisor.py` wires all 10 agents |
| M4 | Market Analyst + News Agents | ✅ Verified — News Agent had a dormant `AttributeError` bug (fake sentiment since M4), fixed 2026-07 |
| M5 | Quant + Vision Agents | ✅ Verified |
| M6 | Consensus Engine + Risk Agent | ✅ Verified |
| M7 | Execution + Journal (Paper Trading) | ✅ Verified — `paper_trading/worker.py`, `ExecutionAgent`, `JournalAgent` |
| M8 | Memory + Reflection Agents | ✅ Verified — `agents/memory.py` (ChromaDB-backed) and `agents/reflection.py` are both in `PIPELINE_ORDER`, genuinely invoked every run, not dangling code |
| M9 | Backtest Engine | ✅ Verified — `backtesting/engine.py` (597 lines), wired into `backend/routers/backtest.py`. **Open decision:** this is a custom pure-Python simulator, not VectorBT/Backtrader as `AGENTS.md` specifies — either update the spec or migrate the implementation |
| M10 | API Gateway (FastAPI endpoints) | ✅ Verified |
| M11 | Frontend Dashboard (Next.js) | ✅ Verified — 16/16 pages exist, confirmed calling real backend endpoints (`frontend/src/lib/api.ts` does real `fetch()`, not mock data) |
| M12 | Live Trading + Safety Gates | ✅ Verified — 4 of 6 exchange connectors (Binance, Bybit, Coinbase, Kraken) are fully functional; Zerodha and IBKR are intentional stubs — connect/balance work, but order placement raises ``NotImplementedError`` (see "Genuinely open items" below). Kill-switch drawdown tests fixed 2026-07. ``/paper_record`` refactored to delegate through the engine the same week. |
| M13 | Monitoring, CI/CD & Security Hardening | ✅ Verified — Prometheus + Grafana in `docker/monitoring/`, CI now runs the *full* suite (the `--ignore=tests/test_live_trading` exclusion was removed after discovering it had been there since the tests were written) |

## Reconciliation note

Git branch names in this repo's history use a different milestone numbering than this
table (e.g. `feat/m8-paper-trading` ≈ this table's M7; `codex/m14-safety-operability`
≈ an expansion/hardening pass on this table's M12). If you're reading commit history
and the milestone number doesn't match this table, trust this table — it's the one
kept in sync with verified status, not branch-naming convention at the time.

## Genuinely open items (not milestones — incremental work)

- **Backtest engine spec decision** (see M9 above): keep the custom simulator or adopt VectorBT/Backtrader.
- **Security hardening depth unconfirmed**: `backend/core/security.py`, `rate_limit.py`, `auth.py` exist; scope/coverage of what they actually enforce hasn't been independently audited.
- **Vision Agent has no fallback model** — `nemotron-nano-12b-v2-vl` is the only vision-capable model in the roster (flagged in `AGENTS.md` itself). Degrades gracefully today; a second VL-capable free model would remove the single point of failure.
- **Zerodha and IBKR real implementations**: Stub connectors now have dedicated tests (22 tests, 1.2s), emit a loud warning when selected, and are removed from the coverage-omit list. The remaining gap is implementing ``create_order`` / ``cancel_order`` / ``get_order_status`` / ``cancel_all_orders`` against the real APIs so these can be selected for live trading.
- **Slow tests**: the conftest ``autouse=True`` Redis-timeout issue (which caused stub tests to take 573s) has been fixed. Some ``live_trading/`` exchange test files may still take 60-110s due to connection-attempt timeouts before mocks engage — a mock-ordering fix would bring those down.
- **Ongoing loop backlog**: see `.agents/workflows/improvement-loop.md` Section 3 for anything currently in flight.

## How to keep this file honest

Before marking anything "✅" here, verify it — don't infer from a prior report, a
branch name, or a milestone number appearing in code. Check for the actual file,
confirm it's imported/called from somewhere real (not just defined), and run its
tests if any exist. This file has been wrong in both directions before: prematurely
"done" early on, and prematurely called "not done" more recently.
