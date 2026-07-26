# ARES AI — Upgrade Summary

## Overview

This upgrade adds three major capabilities to ARES AI:
1. **ML-powered market prediction** via the Kronos foundation model
2. **Web search data collection** via DuckDuckGo (free, no API key)
3. **Browser automation** via browser-use (optional, install on demand)

Additionally, a **Supabase backend service** is provided as an optional alternative
for database and auth.

---

## 1. Kronos Market Predictor

**Files created:**
- `agents/kronos_predictor.py` — KronosPredictorAgent + KronosPredictorInput
- `agents/state.py` — added `KronosOutput` schema

**What it does:**
- Uses the Kronos foundation model (NeoQuasar/Kronos-small) to predict future OHLCV prices
- Kronos is trained on data from 45+ global exchanges (24.7M params, MIT license)
- Falls back to linear trend analysis when the model is unavailable
- Follows the same pattern as MarketAnalystAgent/QuantAgent with typed schemas

**Usage:**
```python
from agents.kronos_predictor import KronosPredictorAgent, KronosPredictorInput

agent = KronosPredictorAgent(ingestor=ingestor)
result = await agent.run(KronosPredictorInput(symbol="BTC-USD", pred_len=24))
```

**API endpoint:** `POST /api/v1/predict/kronos`

**Install dependencies:**
```bash
pip install torch huggingface_hub safetensors einops
# or: pip install -e ".[ml]"
```

**Model:** Auto-downloaded from HuggingFace on first use (~400MB disk, requires
torch). Falls back gracefully with trend-based prediction when not installed.

---

## 2. Web Search (DuckDuckGo)

**Files created:**
- `backend/data/sources/web_search.py` — DuckDuckGoSearcher + WebSearchProvider

**What it does:**
- Free web search via DuckDuckGo (no API key required)
- Falls back from duckduckgo_search library to raw HTTP requests
- Provides financial news search, company info search, macro economic search
- Used by the NewsAgent as a fallback when Yahoo Finance news is unavailable

**Files modified:**
- `agents/news.py` — added web search fallback when Yahoo news returns empty
- `backend/data/sources/registry.py` — imported DuckDuckGoSearcher

**Usage:**
```python
from backend.data.sources.web_search import get_web_search_provider

provider = get_web_search_provider()
results = await provider.searcher.search_financial_news("AAPL")
```

**API endpoints:**
- `GET /api/v1/research/market-context?symbol=AAPL` — comprehensive context
- `POST /api/v1/research/web-search` — general purpose search

**Install optional dependency (for better results):**
```bash
pip install duckduckgo-search
```

---

## 3. Browser Automation (browser-use)

**Files created:**
- `agents/web_collector.py` — WebCollectorAgent + SimpleDataCollector

**What it does:**
- Uses browser-use library to navigate websites and extract data
- Handles JavaScript-rendered pages and multi-step data collection
- Falls back gracefully when browser-use is not installed
- Includes SimpleDataCollector for lightweight HTTP-based fetching

**API endpoint:** `POST /api/v1/collect/web-data`

**Install dependencies:**
```bash
pip install browser-use playwright
playwright install
# or: pip install -e ".[web-automation]"
```

---

## 4. Supabase Backend (optional)

**Files created:**
- `backend/services/supabase_service.py` — SupabaseService

**What it does:**
- Provides Supabase as an alternative backend for auth and database
- Supports email/password auth, PostgreSQL CRUD, realtime subscriptions, file storage
- Gracefully returns None when supabase-py is not installed

**Usage:**
```python
from backend.services.supabase_service import get_supabase_service

svc = get_supabase_service()
if svc:
    user = await svc.sign_in(email, password)
```

**Install dependencies:**
```bash
pip install supabase
# or: pip install -e ".[supabase]"
```

**Environment variables:**
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-or-service-key
```

---

## New API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/predict/kronos` | ML-powered OHLCV price prediction |
| GET | `/api/v1/research/market-context` | Comprehensive market context with web search |
| POST | `/api/v1/research/web-search` | General-purpose web search |
| POST | `/api/v1/collect/web-data` | Browser-based data collection |

## Modified Files

| File | Change |
|------|--------|
| `agents/state.py` | Added `KronosOutput` schema |
| `agents/__init__.py` | Added `KronosPredictorAgent`, `KronosPredictorInput`, `KronosOutput` exports |
| `agents/news.py` | Added web search fallback for news fetching |
| `backend/main.py` | Registered new predictions router |
| `backend/routers/analysis.py` | Registered kronos_predictor and web_collector agents |
| `backend/data/sources/registry.py` | Imported DuckDuckGoSearcher |
| `pyproject.toml` | Added dependencies: duckduckgo-search, optional deps for ml/web-automation/supabase |
