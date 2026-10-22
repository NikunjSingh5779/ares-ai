<!-- docs/00-INDEX.md -->
# docs/ — Index

The ICM layer: navigation, contracts, state, decisions. Code lives elsewhere; these
files point at it. Start at the repo-root `AGENTS.md`.

## ICM core

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
| `architecture.md` | Historical M1 target — now a pointer to `03-ARCHITECTURE.md` | Never (historical) |

## Conventional reference docs

These are concise, task-oriented companions to the ICM core. The numbered docs
above remain the canonical source of truth for rules, status, architecture, and
decisions; these files route and summarize.

| File | Job |
|---|---|
| `PRD.md` | Product summary; full mandate is `01-SPEC.md` |
| `FEATURES.md` | Feature-by-feature status map |
| `SETUP.md` | Local environment and first-run guide |
| `API.md` | Route map and auth conventions; live schema at `/docs` |
| `DATABASE.md` | Tables, migrations, and database invariants |
| `IMPLEMENTATION.md` | Code placement and change-impact map |
| `DEPLOYMENT.md` | Compose stacks, production overlay, bring-up checklist |
| `AUTH_SECURITY.md` | Auth, roles, secrets, live gates, known security gaps |
| `MCP.md` | Project MCP configuration and security rules |
| `INTEGRATIONS.md` | Model providers, data sources, venues, storage |
| `TESTING.md` | Test layout, commands, CI checks |
| `DEBUGGING.md` | Common failures and safe diagnostics |
| `TASKS.md` | Current work queue derived from `05-NEXT.md` |
| `ROADMAP.md` | Roadmap summary; history is `milestone-roadmap.md` |
| `DECISIONS.md` | ADR index; full text is `04-DECISIONS.md` |
| `CONVENTIONS.md` | Engineering and documentation conventions |

## Per-folder contracts

Each working folder has a `CONTEXT.md` stating its inputs, process, outputs, and
human check. The contracts are enforced by `tests/test_icm_structure.py`.
