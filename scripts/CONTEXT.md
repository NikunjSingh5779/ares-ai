<!-- scripts/CONTEXT.md -->
# scripts/ — contract

**Purpose:** operational entry points. Thin wrappers over app modules — no duplicated
business logic, no secrets.

## Files
- `run_live.py` — market poll loop: build pipeline, feed candles, evaluate SL/TP, execute.
- `run_backtest.py` — CLI backtest.
- `simulate_pipeline.py` — offline end-to-end smoke run.
- `test_free_models.py` — validate the roster against the live catalog; also run weekly by
  `.github/workflows/model-catalog.yml`.
- `seed.py` — seed demo data.
- `daily_report.py`, `daily_report_loop.py` — reporting.
- `load_test.py` — API load test.
- `fix_e402.py`, `test_start.py` — one-off diagnostics.

## Invariants
- Import from `agents/`, `backend/`, `paper_trading/`, `live_trading/`; do not re-implement.
- Read config through `configs.settings` and `configs/models.yaml`.
- Safe by default: no live order without the same gates as the API.
- No hardcoded symbols/intervals in a production path (currently `ETH-USD`, `1m`).

## Human check
`python scripts/simulate_pipeline.py` completes without a real key; `run_live.py` logs
the gate decisions for each signal.

## Known gaps
`run_live.py` rebuilds the pipeline per candle and owns a second paper engine. The model
roster check is scheduled weekly, but its first GitHub Actions run is still pending; it
needs the `OPENROUTER_API_KEY` repository secret.
