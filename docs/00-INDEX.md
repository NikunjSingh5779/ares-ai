<!-- docs/00-INDEX.md -->
# docs/ — Index

The ICM layer: navigation, contracts, state, decisions. Code lives elsewhere; these
files point at it. Start at the repo-root `AGENTS.md`.

| File | Job | Update when |
|---|---|---|
| `01-SPEC.md` | Full project mandate (role, rules, gates, output requirements) | A rule changes |
| `02-STATUS.md` | Verified current state + known gaps | Any milestone or state change |
| `03-ARCHITECTURE.md` | Layers, flows, MVC mapping, data ownership, dependency rules | The structure changes |
| `04-DECISIONS.md` | ADR log — why the structure is this way | A structural decision is made |
| `05-NEXT.md` | Prioritized work plan with acceptance criteria | Priorities change |
| `milestone-roadmap.md` | Milestone-by-milestone history | A milestone is verified |
| `map/AGENTS.md` | Codebase object + process map (change-impact) | A mapped object/process changes |
| `design.md` | Visual identity system (factory reference for frontend + landing) | Brand changes |
| `architecture.md` | M1 target architecture — **superseded** by `03-ARCHITECTURE.md` | Never (historical) |

## Per-folder contracts

Each code folder states its own job in a `CONTEXT.md`: what it reads, what it does,
what it writes, and what a human checks. See any `CONTEXT.md` for the pattern.

## Rules for this folder

- One home per fact. If a fact lives here and in code, code wins and the doc links to it.
- No code in `docs/`. No prose dumps in `AGENTS.md`.
- Numbered files are the reading order; unnumbered files are references.
- Every relative link must resolve. `tests/test_icm_structure.py` enforces this.
