<!-- frontend/CONTEXT.md -->
# frontend/ — contract

**Purpose:** the Next.js dashboard. Views render; `lib/` talks to the API; `types/` defines shapes.

## Layout (MVC)
| Role | Path |
|---|---|
| Views | `src/app/**/page.tsx`, `src/app/layout.tsx`, `src/components/` |
| Auth | `src/app/login/page.tsx`, `src/components/AuthGate.tsx`, `src/lib/auth.ts` |
| Controllers | `src/lib/api.ts`, `src/lib/usePipelinePolling.ts` |
| Models | `src/types/api.ts` |
| Style | `src/app/globals.css`, Tailwind; design system in `docs/design.md` |

## Inputs
REST under `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`), SSE for analysis.
The operator enters `API_SECRET_KEY` on `/login`; it is kept in `sessionStorage` and
sent as `X-API-Key`.

## Outputs
Static/SSR pages served by Next; no secrets in the bundle.

## Invariants
- Pages call `lib/api.ts`; no direct `fetch` and **no mock/generated data** in a page.
- Loading, empty, error, and timeout states are explicit.
- Interactive controls have labels/`aria-label`; async updates use `aria-live`.
- Types mirror `backend/schemas`; a new endpoint lands here in the same change.
- No auth secret is bundled. A 401 clears the stored key and redirects to `/login`;
  `AuthGate` blocks protected pages when no key is present.

## Human check
`pnpm build` (in `frontend/`), then click through the changed page. Confirm `/login`
rejects a wrong key and that a protected page redirects without one.

## Known gaps
- `markets/page.tsx` generates candles with `Math.random()` (no market-data API).
- `settings/page.tsx` never persists and shows 10% position size vs backend 2%.
- `strategy-builder/page.tsx` is local-only.
- Zero `aria-label` across pages; no skip link; no frontend tests/lint/typecheck in CI.
