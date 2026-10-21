<!-- configs/CONTEXT.md -->
# configs/ — contract

**Purpose:** the single source of runtime configuration and the model roster.

## Files
- `settings.py` — `Settings` (pydantic-settings), env overrides, `live_trading_enabled`
  (default false), production secret validator.
- `models.yaml` — per-agent primary + fallback chain, timeouts, retry/breaker defaults,
  and `defaults.universal_fallback`.

## Rules
- Model IDs live **only** in `models.yaml` (hard rule #1).
- Secrets come from env; never commit `.env`; keep `.env.example` current.
- Add a setting → `Settings` field + `.env.example` + compose env + a config test.
- Paper fills use `paper_trading_commission_pct` and `paper_trading_slippage_pct`
  (decimal fractions, default 0.001 = 10 bps per side).
- Paper writes wait at most `paper_trading_writer_lock_timeout_seconds` (default 10 s) for
  the cross-process advisory lock; on timeout the API returns 503.
- Production (`ENVIRONMENT=production`) must reject default secrets and default DB
  password. Use `docker-compose.prod.yml` (or `docker/docker-compose.prod.yml`) to set
  it; the development files intentionally do not.
- `API_SECRET_KEY` must be unique in every environment; the shipped default is rejected.

## Inputs
Environment variables / `.env`, YAML.

## Outputs
An immutable `settings` object imported across the app; `load_model_roster()` for agents.

## Human check
`python -c "from configs.settings import settings; print(settings.environment, settings.live_trading_enabled)"`.
`pytest tests/test_config.py tests/test_models.py -q`.

## Known gaps
Model catalog removals are checked manually, not in CI. Production safety depends on
using the explicit Compose overlay; the base development files do not set
`ENVIRONMENT=production`.
