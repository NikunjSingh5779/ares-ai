<!-- docs/CONTEXT.md -->
# docs/ — contract

**Purpose:** the ICM layer. Navigation, contracts, verified state, decisions, plans.
**Contains no executable code.**

## Inputs
- Verified command output (tests, lint, mypy, build) — never a status label.
- Structural decisions from the person who owns the repo.
- `docs/milestone-roadmap.md` as history, not current truth.

## Process
1. Update `02-STATUS.md` when a check is re-run.
2. Add an ADR to `04-DECISIONS.md` before a structural change.
3. Keep `05-NEXT.md` ordered by risk; exit criteria must be testable.
4. Update `map/` when a mapped object or process changes.

## Outputs
- A cold reader can answer “where am I, where do I go” from `AGENTS.md` plus one doc.
- Every relative link resolves.

## Human check
- `pytest tests/test_icm_structure.py -q`
- `AGENTS.md` stays under its line budget; no payload moved back into it.

## Invariants
- One home per fact. Code wins over docs; docs link to code.
- `01-SPEC.md` is the full mandate; `AGENTS.md` is a pointer plus non-negotiables.
- `architecture.md` is historical and marked superseded.
