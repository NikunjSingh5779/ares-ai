<!-- docs/PRD.md — conventional product summary; canonical mandate is 01-SPEC.md -->
# Product Requirements — ARES AI

> This is a concise product summary for onboarding and review. The complete,
> authoritative mandate is `docs/01-SPEC.md`. Verified state and gaps live in
> `docs/02-STATUS.md`; the ordered work plan lives in `docs/05-NEXT.md`.

## Problem

Retail and small operators cannot continuously combine market analysis, news
sentiment, quantitative checks, risk limits, execution, and post-trade review.
Manual workflows are slow, inconsistent, and blind to why a trade happened.

## Product goal

ARES AI is an autonomous, explainable multi-agent trading platform. It turns a
market request into a typed, auditable decision through a fixed agent pipeline,
then records the outcome and lessons learned.

## Users

- **Operator** — runs the stack, sets limits, approves or rejects trades, and
  can stop all live activity with the kill switch.
- **Analyst / researcher** — runs analysis, backtests, paper trades, and
  inspects journals and memory.
- **Engineer** — extends agents, routers, data sources, and the dashboard
  without weakening safety gates.

## Functional requirements

| Area | Requirement |
|---|---|
| Analysis | Run the LangGraph pipeline over a symbol and return typed agent outputs with rationale. |
| Consensus | Approve a trade only when Market Analyst and Quant both exceed 80% confidence, Risk approves, and drawdown/exposure limits pass. |
| Risk | Enforce max drawdown, exposure, position size, and strategy boundaries before execution. |
| Paper trading | Persist portfolio, positions, orders, trade history, and equity to PostgreSQL; simulate commission and slippage. |
| Live trading | Keep one gated order path; require human approval by default; require the paper-trading promotion gate for autonomous mode. |
| Backtesting | Run historical simulations and report Sharpe, Sortino, win rate, profit factor, drawdown, expectancy, and recovery factor. |
| Journal & memory | Record decisions, rationale, outcomes, and lessons in PostgreSQL, Redis, and ChromaDB. |
| Dashboard | Show analysis, markets, signals, portfolio, paper/live trading, risk, journal, memory, agents, logs, analytics, backtests, and settings. |
| Monitoring | Expose `/health`, Prometheus metrics, Grafana dashboards, and audit records for live orders. |
| Self-improvement | Evaluate outcomes after trades and store lessons for future runs. |

## Safety requirements

1. Free-tier models only; model IDs live in `configs/models.yaml`.
2. Every agent input/output is a typed Pydantic schema; trading numbers require
   a `rationale`.
3. No signal means no trade. A failed required agent rejects the trade; it
   never silently approves.
4. Market Analyst and Quant must each exceed 80% confidence.
5. Live trading starts in human-approval mode and is opt-in per strategy after
   the paper-trading promotion gate.
6. The kill switch halts order placement and requires human re-arm.
7. Secrets stay in `.env`; `.env.example` is the only template committed.
8. Model failure degrades gracefully and is logged with the fallback used.
9. Never weaken a safety gate to make a test pass.

## Success metrics

- The pipeline returns schema-valid decisions or explicitly rejects them.
- Paper state survives restarts and concurrent writers without lost updates.
- The suite, Ruff, mypy, frontend build, and Compose validation are green in CI.
- No page renders fabricated market data or fake settings (Phase 2 exit).
- Live trading cannot start without every gate passing.

## Out of scope / current boundaries

- Real-capital trading is disabled by default and is not part of Phase 2.
- The system is not financial advice and does not manage third-party funds.
- Zerodha and Interactive Brokers connectors are intentional stubs for order
  placement; Binance, Bybit, Coinbase, and Kraken are implemented.
- The backtest engine is a custom pure-Python simulator; whether to adopt
  VectorBT/Backtrader remains an open decision (see `docs/milestone-roadmap.md`).

## Related documents

- Full mandate and rules: `docs/01-SPEC.md`
- Verified state: `docs/02-STATUS.md`
- Features and status: `docs/FEATURES.md`
- Architecture: `docs/03-ARCHITECTURE.md`
- Decisions: `docs/04-DECISIONS.md` and `docs/DECISIONS.md`
- Plan: `docs/05-NEXT.md` and `docs/TASKS.md`
