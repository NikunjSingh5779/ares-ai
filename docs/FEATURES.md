<!-- docs/FEATURES.md — feature status map; verified state lives in 02-STATUS.md -->
# Features — status map

> Status labels describe the current verified implementation, not the target
> product. `docs/02-STATUS.md` is the source of truth for measured checks;
> `docs/05-NEXT.md` is the ordered plan. “Partial” means it works but a known
> gap remains.

## Core pipeline

| Feature | Status | Notes |
|---|---|---|
| LangGraph supervisor and fixed pipeline order | Working | `agents/supervisor.py`, `PIPELINE_ORDER` |
| Market Analyst, Quant, News, Vision agents | Working | Vision is advisory; degraded mode is explicit |
| Deterministic consensus gate | Working | Market Analyst and Quant must both exceed 80%; no LLM in the gate |
| Risk gate | Working | Drawdown, exposure, position size, strategy boundaries |
| Execution and Journal agents | Working | Paper path persists; live path is gated |
| Reflection and Memory agents | Working | Reflection reviews outcomes; memory uses ChromaDB |
| Model fallback, retry, backoff, circuit breaker | Working | Roster in `configs/models.yaml`; universal free fallback appended |
| Typed Pydantic I/O with rationale | Working | Trading-relevant numbers require explanation |

## Trading and portfolio

| Feature | Status | Notes |
|---|---|---|
| Paper portfolio, positions, orders | Working | PostgreSQL is the durable source; API reads hydrate |
| Paper fills with commission and slippage | Working | Equity-based PnL; marks open positions |
| Concurrent paper writers | Working | In-process + transaction-scoped advisory lock; busy writer -> 503 |
| Duplicate order protection | Working | Required `client_order_id`; duplicate -> 409 |
| Restart-safe paper state | Working | Phase 1 Compose exit passed on 2026-10-21 |
| Backtesting | Working | Custom pure-Python simulator; library choice remains open |
| Live trading controls | Gated / not enabled | One order path; kill switch, human approval, promotion, exchange gates |
| Exchange connectors | Partial | Binance, Bybit, Coinbase, Kraken implemented; Zerodha and IBKR order methods are stubs |
| Promotion gate | Working | 30 trading days or 50 closed paper trades, whichever is longer |

## Research and intelligence

| Feature | Status | Notes |
|---|---|---|
| Market data ingestion | Working | Yahoo Finance, CoinGecko, and Binance public API are in the source registry; DuckDuckGo supplies news fallback. Reddit, RSS, and Fear & Greed are spec targets, not all wired yet. |
| Technical indicators and candlesticks | Working | `agents/indicators.py`, `agents/candlesticks.py` |
| Web research / DuckDuckGo | Working | Research endpoints; treat external content as untrusted data |
| Kronos OHLCV forecasting | Optional | Downloads `NeoQuasar/Kronos-small` on first use; not required by the core pipeline |
| Improvement engine | Working | Suggestions and metrics persist in `reflection_runs`/`improvement_records`; a best-effort post-run hook analyzes committed history. Apply only marks a record; it never changes configuration or a safety limit. |
| Strategy builder | Working | Drafts persist through `/api/v1/strategies`; only draft/paused rows are editable and live/promotion fields stay server-owned |
| Chat interface | Working | Read-only multi-turn `POST /api/v1/chat` with a free-tier fallback chain plus an opt-in local fallback; no tools or execution path |

## Dashboard

| Page | Status | Notes |
|---|---|---|
| Dashboard, portfolio, signals, risk, journal, memory, analytics | Working | Reads backend endpoints |
| Markets | Working | Real candles from `/api/v1/market/candles` (Binance for crypto, Yahoo for equities); analysis is an explicit action; chart disposes on unmount |
| Paper trading | Working | Uses the paper ledger path |
| Live trading | Partial | Status/audit and controls are real; polling is concurrent, single-flight, pause-aware, and abortable. Execution remains paper-only and disabled by default. |
| Agents and logs | Working | Agent status and logs endpoints |
| Backtests | Working | Calls the backtest endpoint |
| Settings | Working | Loads/saves `app_settings` through authenticated GET/PUT; safety limits (including the 2% cap) are read-only; default symbol and live refresh are wired into the pages |
| Strategy builder | Working | Real load/save against `strategies`; unsupported backtest types fail honestly |
| Chat | Working | Multi-turn read-only assistant; history is client-held and sent per request; model/fallback metadata is shown; opt-in local `local_chat` fallback |

## Platform and operations

| Feature | Status | Notes |
|---|---|---|
| API-key auth on non-public routes | Working | Empty/default key -> 503; missing key -> 401 |
| JWT login and roles | Working | `viewer`, `operator`, `admin`, `super_admin`; role changes apply on next login |
| Live-control role gate | Working | Kill/arm/start/stop/mode; credential-only so kill works during DB outage |
| Health and metrics | Working | `/health` 503 on dependency failure; Prometheus `/metrics`; JSON `/api/v1/metrics` |
| Security headers, CORS, rate limiting | Working | Middleware in `backend/main.py`; login rate limiter |
| Docker Compose stacks | Working | 7-service dev stack, 11-service root stack, production overlays |
| CI | Working | lint, test, postgres-integration, frontend lint/typecheck/test/build, docker validation |
| Frontend lint/typecheck/test in CI | Working | ESLint 9 flat config, `tsc --noEmit`, and 18 Vitest tests run before `pnpm build` |
| Automated deployment | Not present | CI validates; deployment is manual |
| Grafana / Prometheus dashboards | Working | `docker/monitoring/`; alert rules are Phase 3 |

## Known gaps that affect feature claims

- `/execute` trusts the authenticated caller's agent payload; a signed or stored
  approval is a P2 design item.
- The kill-switch arm epoch is process-local; a shared Redis epoch is P1 work.
- `/analyze` uses a module-global `_last_state`; concurrent runs are not
  isolated and have no cost budget.
- Pre-P1-A short positions migrated as long need manual reconciliation.
- Paper realism lacks gap-through stop fills, partial fills/liquidity,
  borrow/funding costs, and per-symbol slippage.

## Read next

- Verified counts and gaps: `docs/02-STATUS.md`
- Work order: `docs/05-NEXT.md` and `docs/TASKS.md`
- Architecture: `docs/03-ARCHITECTURE.md`
