<!-- docs/INTEGRATIONS.md — external systems and how ARES AI uses them -->
# Integrations — ARES AI

> This is a map of external systems. Provider credentials and endpoints belong
> in `.env`; model IDs belong in `configs/models.yaml`. Never commit real keys.

## AI model providers

| Provider | Role | Configuration |
|---|---|---|
| OpenRouter | Primary free-tier model catalog and universal fallback | `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `configs/models.yaml` |
| OpenCode | Optional fallback provider | `OPENCODE_API_KEY`, `OPENCODE_BASE_URL` |

The roster assigns each agent a primary model and ordered fallbacks. The
`AgentModelConfig` layer appends the universal fallback
`open_router/openrouter/free` after every explicit chain. Reliability behavior
includes per-model circuit breakers, exponential backoff with jitter, capped
retries, and per-model rate limiting. Failures are logged to `agent_logs` with
the model, error type, latency, and fallback used.

Validate the roster with:

```powershell
uv run python scripts/test_free_models.py --dry-run
uv run python scripts/test_free_models.py
```

Free models are routinely deprecated or rate-limited; a full chain failure
rejects the trade rather than approving it.

## Market and research data

| Source | Current use |
|---|---|
| Yahoo Finance | Equities/indices OHLCV and news headlines |
| CoinGecko | Crypto market data |
| Binance public API | Crypto OHLCV/market data |
| DuckDuckGo (free search) | Web research and news fallback |
| Reddit, RSS feeds, Fear and Greed Index | Listed as target sources in `01-SPEC.md`; not all are wired into the current source registry |
| Kronos (`NeoQuasar/Kronos-small`) | Optional OHLCV forecasting; downloads on first use |

Data ingestion lives in `backend/data/` (`ingestor.py`, `sources/`). The current
source registry contains Yahoo Finance, CoinGecko, Binance, and the free web
search provider. News uses Yahoo headlines and falls back to DuckDuckGo.

## Execution venues

| Venue | Connector status |
|---|---|
| Binance | Implemented (ccxt) |
| Bybit | Implemented (ccxt) |
| Coinbase | Implemented |
| Kraken | Implemented |
| Zerodha | Intentional stub for order placement; connect/balance work |
| Interactive Brokers | Intentional stub for order placement; connect/balance work |

Live trading is disabled by default (`LIVE_TRADING_ENABLED=false`). Every live
order passes the kill switch, mode, promotion, and exchange gates and is
audited. The only production `exchange.create_order` call site is
`live_trading/engine.py`.

## Storage and infrastructure

| System | Role |
|---|---|
| PostgreSQL 16 | Durable users, portfolio, positions, orders, signals, trade history, journal, memory metadata, market data, metrics, backtests |
| Redis | Cache, queueing, live kill-switch state |
| ChromaDB 1.5.9 | Vector store for long-term memory (`/data` volume) |
| Prometheus | Metrics scrape target (`/metrics`) |
| Grafana | Dashboards over Prometheus |
| Docker Compose | Development, full, and production-overlay stacks |
| nginx | Reverse proxy in the full root stack |

## Frontend and content

| System | Role |
|---|---|
| Next.js 16 dashboard | Operator UI at `http://localhost:3000`; calls `NEXT_PUBLIC_API_URL` |
| Astro landing page | Marketing page at `http://localhost:4321` |
| TradingView Lightweight Charts | Market chart rendering; `/markets` loads real candles from `GET /api/v1/market/candles` |

## Web research and MCP

- Web research uses a free search path and stores results as untrusted data.
- PostgreSQL MCP is documented in `docs/MCP.md`; it is a local development tool,
  not part of the trading path.
- No integration may bypass the typed agent pipeline or a safety gate.

## Adding an integration

1. Define the typed request/response schema first.
2. Add the secret to `.env.example` with a placeholder and to `.env` locally.
3. Implement the adapter behind a documented interface; do not call the
   external service from a router or a page.
4. Add a failure/degradation path (timeout, retry, fallback, or explicit
   rejection).
5. Add tests with mocked network calls.
6. Document the integration here and in the routed `CONTEXT.md`.
7. Never add a live-trading path that bypasses `execute_signal`.

## Read next

- Model roster: `configs/models.yaml`
- Architecture: `docs/03-ARCHITECTURE.md`
- Security: `docs/AUTH_SECURITY.md`
- Setup: `docs/SETUP.md`
