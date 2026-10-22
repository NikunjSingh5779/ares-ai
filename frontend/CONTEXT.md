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
- Loading, empty, error, and timeout states are explicit. `api.ts` gives every request
  a bounded timeout and exposes typed `ApiError`/`ApiTimeoutError`; unmounting callers
  pass an `AbortSignal`.
- Polling is single-flight. `/live` pauses while the document is hidden, resumes on
  visibility, and force-refreshes after control actions; `usePipelinePolling` starts
  after the POST is accepted, aborts on unmount, and backs off under its 60 s timeout.
- Interactive controls have labels/`aria-label`; async updates use `aria-live`; dialogs
  use `role="dialog"` with an accessible title and initial focus.
- Types mirror `backend/schemas`; a new endpoint lands here in the same change.
- No auth secret is bundled. A 401 clears the stored key and redirects to `/login`;
  `AuthGate` blocks protected pages when no key is present.

## Human check
`pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build` (in `frontend/`), then
click through the changed page. Confirm `/login` rejects a wrong key and that a
protected page redirects without one. On `/markets`,
confirm the chart loads real candles from `/api/v1/market/candles`, the symbol change
does not start an analysis, and the **Analyze** button is the only trigger. On
`/settings`, confirm the page loads the 2% safety cap, save a different default symbol
and refresh interval, reload, and see the saved values; confirm no secret or fake
WebSocket preview is rendered. On `/live`, confirm status and audit update together,
hiding the tab pauses refresh, Escape closes the kill/arm dialogs, and keyboard focus
starts on Cancel. Use the skip link with the keyboard and verify it focuses the main
content. On `/strategy-builder`, save a draft, reload the page, confirm it appears in
Saved Drafts, edit it, and confirm the version increases. Confirm an unsupported
backtest type shows a disabled explanation instead of navigating to an invalid run.

## Known gaps
- `/strategy-builder` persists drafts, but its parameters are not yet consumed by the
  backtest engine; the handoff passes only the supported strategy type.
- The chat page triggers `POST /api/v1/analyze` and shows the accepted status; it is
  not yet a multi-turn conversational agent.
- A manual axe/Lighthouse pass has not been run; lint and Vitest are now automated
  (`eslint . --max-warnings=0`, `tsc --noEmit`, `vitest run`) but no browser-based
  accessibility audit is configured.
- The style guide still uses a small number of direct hex colors; the muted-text values
  were raised for contrast, but a full design-token sweep remains optional polish.
