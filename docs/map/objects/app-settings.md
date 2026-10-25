<!-- docs/map/objects/app-settings.md -->
# Dashboard preferences (`app_settings`)

**What it is:** the singleton PostgreSQL row that persists non-safety dashboard
preferences across restarts. It is deliberately not a trading configuration store.

**Homes:**
- `database/schema.sql` / `database/init.sql` — `app_settings` table, one-row constraint,
  `updated_at` trigger.
- `migrations/versions/0005_app_settings.py` — additive migration and seed row.
- `backend/schemas/settings.py` — `DashboardPreferences` (mutable) and `SafetyLimits`
  (read-only response).
- `backend/services/settings_service.py` — load/merge/upsert and corrupt-row fallback.
- `backend/routers/settings.py` — authenticated `GET /api/v1/settings` and
  `PUT /api/v1/settings/preferences`.
- `frontend/src/app/settings/page.tsx` — real load/save UI; dashboard, markets, and live
  pages read the preferences.

**Shape:** one row (`id = 1`) with `preferences JSONB` and `updated_at TIMESTAMPTZ`.
Current keys: `default_symbol` (1–20 chars, normalized uppercase) and
`live_refresh_seconds` (5–30).

**Writers:** `settings_service.save_preferences` via the PUT route; the trigger updates
`updated_at`. No trading path writes this table.

**Readers:** the settings route, dashboard quick analysis, the initial markets chart, and
the live-page polling interval. Trading, risk, consensus, execution, and live gates never
read it.

**Invariants:**
- The API body is `DashboardPreferences` with `extra="forbid"`; a `safety` object or any
  cap/threshold field is a 422 and writes nothing.
- `SafetyLimits` is computed from `agents.risk`, `agents.consensus`, and
  `configs.settings`; the 2% position cap is not environment-configurable.
- Missing, corrupt, or invalid stored JSON falls back to defaults; a store failure is 503.
- New defaults merge over an older stored object, so a preference added later does not
  require a data migration.
- Preferences are global to this single-user deployment; the shared API key has no user row.

**Change impact:**
- Add a preference → schema field in `DashboardPreferences`, a default, the consuming page,
  `frontend/src/types/api.ts`, and router/service tests.
- Change a safety limit → the enforcing module (`agents.risk`, `agents.consensus`) or
  `configs.settings`; never `app_settings`.
- Change the table → `schema.sql` + `init.sql` + a new migration; never edit `0005` after
  it ships.

**Tests:** `tests/test_settings_router.py`, `tests/test_settings_service.py`,
`tests/test_schema.py`, `tests/test_security/test_route_auth.py`, and
`tests/test_config.py`.

**Known gaps:** preferences are global to this single-user deployment; there is no
per-user override. The shared request wrapper now applies a bounded timeout and accepts
an `AbortSignal`, so a hung settings request fails explicitly instead of waiting
indefinitely.
