# ARES AI — Architecture Overview

> **Milestone:** M1 — Infrastructure Foundation
> **Status:** Initial scaffolding. Agent pipeline and API endpoints to be built in M3+.

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                    │
│               (Frontend — M11)                          │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    API Gateway Layer                     │
│                (FastAPI — M10)                           │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    Supervisor Agent                      │
│               (LangGraph — M3)                           │
└─────┬──────────┬──────────┬──────────┬──────────────────┘
      │          │          │          │
┌─────▼──┐ ┌────▼───┐ ┌───▼────┐ ┌───▼─────────┐
│ Market │ │ Quant  │ │  News  │ │   Vision    │
│ Analyst│ │ Agent  │ │ Agent  │ │   Agent     │
│  (M4)  │ │  (M5)  │ │  (M4)  │ │   (M5)      │
└────┬───┘ └───┬────┘ └───┬────┘ └───┬─────────┘
     └─────────┴──────────┴──────────┘
                         │
               ┌─────────▼──────────┐
               │  Consensus Engine  │
               │       (M6)         │
               └─────────┬──────────┘
                         │
               ┌─────────▼──────────┐
               │    Risk Agent      │
               │       (M6)         │
               └─────────┬──────────┘
                         │
               ┌─────────▼──────────┐
               │   Execution Agent  │
               │  Paper/Live (M7)   │
               └─────────┬──────────┘
                         │
               ┌─────────▼──────────┐
               │   Journal Agent    │
               │       (M7)         │
               └─────────┬──────────┘
                         │
               ┌─────────▼──────────┐
               │  Reflection Agent  │
               │       (M8)         │
               └─────────┬──────────┘
                         │
               ┌─────────▼──────────┐
               │   Memory Agent     │
               │       (M8)         │
               └────────────────────┘
```

## Layer Stack

| Layer | Technology | Milestone |
|-------|------------|-----------|
| Infrastructure | Docker Compose, PostgreSQL 16, Redis 7, ChromaDB | M1 |
| Data Ingestion | Yahoo Finance, CoinGecko, Binance APIs | M2 |
| Agent Framework | LangGraph, Pydantic I/O contracts | M3 |
| API Gateway | FastAPI | M10 |
| Frontend | Next.js, TailwindCSS, TradingView Charts | M11 |
| Monitoring | Prometheus, Grafana | M13 |

## Data Flow

1. **Data Ingestion** (M2) collects market data → `market_data` table + Redis cache
2. **Supervisor** (M3) receives a request, initializes state, dispatches to agents
3. **Market Analyst + News + Quant + Vision** (M4-M5) run in parallel, produce typed outputs
4. **Consensus Engine** (M6) aggregates signals → rejects if any required agent failed or confidence < 80%
5. **Risk Agent** (M6) validates position sizing, drawdown, exposure
6. **Execution** (M7) places paper or live trade → logs to `orders`, `trade_history`
7. **Journal** (M7) records the trade with full agent rationale chain
8. **Reflection** (M8) evaluates prediction vs outcome → stores lessons
9. **Memory** (M8) consolidates into ChromaDB + `memories` table

## Agent I/O Contracts

Every agent receives and returns strictly typed Pydantic models (see `agents/state.py`):

| Agent | Input Slice | Output Model |
|-------|-------------|--------------|
| Market Analyst | Symbol + market data | `MarketAnalystOutput(confidence, direction, indicators, rationale)` |
| Quant | Symbol + market data + analyst output | `QuantOutput(confidence, direction, expected_return, params, rationale)` |
| News | Symbol | `NewsOutput(sentiment, key_events, impact_scores, rationale)` |
| Vision | Symbol + chart image | `VisionOutput(chart_pattern, confidence, support, resistance, available)` |
| Consensus | All agent outputs | `ConsensusOutput(approved, composite_confidence, agreement_metrics)` |
| Risk | Signal + portfolio state | `RiskOutput(approved, max_position_size, stop_loss, risk_score, rationale)` |

## Safety Gates (M12)

- **Default:** Human approval mode for all new strategies/accounts
- **Paper→Live promotion:** Minimum 30 trading days OR 50 closed paper trades
- **Kill switch:** Global manual + automatic on drawdown breach
- **No silent trade approval:** Agent failure → trade rejected, logged as "no-trade: agent unavailable"

## Deferred to Future Milestones

| Component | Milestone | Reason |
|-----------|-----------|--------|
| Real agents (market analyst, quant, etc.) | M3-M8 | Need the LangGraph framework first |
| Full API endpoints | M10 | M1 provides only stub routes |
| Authentication | M3 | Dev-only stub in M1 |
| Market data ingestion | M2 | Needs table plus data-layer code |
| Frontend | M11 | Needs the API first |
