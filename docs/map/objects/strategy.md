# Strategy drafts (`strategies`)

**What it is:** the persisted configuration for a trading strategy draft. It is
not an order, a signal, or a promotion decision. Saving a draft never enables live
trading or changes a safety gate.

**Homes:**
- `database/schema.sql` / `database/init.sql` — existing `strategies` table
  (`name`, `description`, `strategy_type`, `config JSONB`, `parameters JSONB`,
  `version`, `status`, promotion counters, `live_trading_enabled`).
- `backend/schemas/strategy.py` — `StrategyCreate`, `StrategyUpdate`,
  `StrategyConfig`, `StrategyParameters`, and `StrategyResponse`.
- `backend/services/strategy_service.py` — list/get/create/update SQL and row
  conversion; only `draft`/`paused` rows are editable.
- `backend/routers/strategies.py` — authenticated `/api/v1/strategies` routes.
- `frontend/src/app/strategy-builder/page.tsx` — real save/load UI, saved-draft
  list, and backtest handoff; `frontend/src/lib/api.ts` and `types/api.ts` mirror
  the backend.
- `frontend/src/app/backtests/page.tsx` — consumes the `?strategy=` handoff for
  supported backtest types.

**Shape:** one row per draft. `config` currently holds `indicators: string[]`.
`parameters` holds `position_size_pct`, `stop_loss_pct`, and `take_profit_pct`.
`version` increments on every edit. `status` defaults to `draft`; the API never
sets it.

**Writers:** `strategy_service.create_strategy` and `update_strategy` via the
router. The database trigger updates `updated_at`. No trading or execution path
writes this table as part of a trade.

**Readers:** the strategy-builder page and the backtest handoff. Risk, consensus,
execution, live safety, and promotion do not read draft configuration from this
surface.

**Invariants:**
- Request models use `extra="forbid"`; `status`, `live_trading_enabled`, and
  promotion fields are **422** and write nothing.
- `live_trading_enabled` is never set by this API; promotion remains a separate
  gated process.
- Only `draft` and `paused` rows can be edited; other statuses return **409**.
- `position_size_pct` is a draft input, not a safety override. The 2% cap, risk
  score, drawdown, exposure, promotion gate, and kill switch still apply at trade
  time.
- A missing strategy returns **404**; a store failure returns **503**.

**Change impact:**
- Add a draft field — schema model, request validation, service SQL, response
  types, frontend form, and tests.
- Change editable statuses — service `_EDITABLE_STATUSES` and router tests first;
  never widen this to live trading without the promotion gate.
- Change the table — update both SQL files, a new migration, the map card, and
  schema tests. Do not edit the shipped initial migration.

**Tests:** `tests/test_strategy_service.py`, `tests/test_strategy_router.py`,
`tests/test_postgres_strategy_integration.py`, `tests/test_security/test_route_auth.py`,
`tests/test_schema.py`, and `tests/test_icm_structure.py`.

**Known gaps:** draft parameters are stored but not yet consumed by the backtest
engine (the handoff passes only the strategy type). The real-PostgreSQL module
covers create/list/get/update, JSONB round-trips, version bumps, lifecycle-field
422s, the 409 promotion boundary, and 404s; the service unit tests still use a
mock session for SQL-shape assertions.
