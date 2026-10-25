<!-- landing/CONTEXT.md -->
# landing/ — contract

**Purpose:** the public Astro marketing page. Not part of the trading runtime.

## Layout
- `src/pages/index.astro` — the page.
- `src/components/` — `Navbar`, `Hero`, `Features`, `Footer`.
- `src/layouts/Layout.astro` — shell.
- `src/styles/global.css` — styles; visual language follows `docs/design.md`.
- `public/` — favicons. `dist/` is build output.

## Inputs
Static content; no backend API calls.

## Outputs
Static site in `dist/` (deploy target chosen outside this repo).

## Invariants
- No live trading claims beyond what the product does; no fake metrics.
- Follows the shared visual identity; do not fork the palette.
- No secrets or analytics keys in source.

## Human check
`npm run dev` (port 4321) or `npm run build && npm run preview`.

## Tests
None. Build is the gate.
