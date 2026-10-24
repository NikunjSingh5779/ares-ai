<!-- configs/CONTEXT.md -->
# configs/ — contract

**Purpose:** the single source of runtime configuration and the model roster.

## Files
- `settings.py` — `Settings` (pydantic-settings), env overrides, `live_trading_enabled`
  (default false), production secret validator.
- `models.yaml` — per-agent primary + fallback chain, timeouts, retry/breaker defaults,
  `defaults.universal_fallback`, and the separate opt-in `local_chat` entry.

## Rules
- Model IDs live **only** in `models.yaml` (hard rule #1).
- Secrets come from env; never commit `.env`; keep `.env.example` current.
- Add a setting → `Settings` field + `.env.example` + compose env + a config test.
- `local_llm_enabled` is opt-in (`false`) and chat-first. `local_llm_base_url` points at
  the local OpenAI-compatible server; `local_llm_max_concurrent` gates the single-request
  model process-wide. Model IDs still live only in `models.yaml`.
- Paper fills use `paper_trading_commission_pct` and `paper_trading_slippage_pct`
  (decimal fractions, default 0.001 = 10 bps per side).
- Position sizing is **not** an environment setting. `agents.risk.MAX_POSITION_SIZE_PCT`
  (2% of paper equity) is the single source of truth; `app_settings` preferences cannot
  change it.
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
`python -c "from configs.settings import settings; print(settings.environment, settings.live_trading_enabled, settings.local_llm_enabled)"`.
`pytest tests/test_config.py tests/test_models.py -q`.

## Known gaps
Model catalog removals are checked manually, not in CI. Production safety depends on
using the explicit Compose overlay; the base development files do not set
`ENVIRONMENT=production`.
