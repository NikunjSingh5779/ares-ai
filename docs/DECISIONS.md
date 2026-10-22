<!-- docs/DECISIONS.md — conventional ADR index; canonical ADR log is 04-DECISIONS.md -->
# Decisions — ADR index

> The canonical, full ADR log is [`04-DECISIONS.md`](04-DECISIONS.md). This file
> is a one-screen index so a reader can find the decision that shaped a rule
> without opening the full history. When adding an ADR, write it in
> `04-DECISIONS.md` and add one line here.

## Architecture and documentation

| ADR | Decision | Consequence |
|---|---|---|
| ADR-001 | Adopt ICM for navigation and MVC for code placement | Docs route; folders state contracts; code placement follows MVC roles |
| ADR-002 | Do not move code during the restructure | Structure changes are separate, explicitly approved work |
| ADR-003 | The root entry file routes; the mandate lives on a shelf | `AGENTS.md` stays small; `01-SPEC.md` owns the full rules |
| ADR-004 | Status is a verified file, not a label | `02-STATUS.md` records measured results and dates |
| ADR-008 | Structure is enforced by a test, not by convention | `tests/test_icm_structure.py` checks contracts, entry budget, links |

## Data and execution

| ADR | Decision | Consequence |
|---|---|---|
| ADR-005 | One portfolio source of truth | PostgreSQL paper ledger is durable; the in-memory engine is a cache |
| ADR-006 | Every live order goes through one gate | One production `create_order` call site; no alternate live path |
| ADR-012 | Paper PnL is equity-based, with costs and marks | Fees, slippage, short proceeds, and mark-to-market are part of paper results |
| ADR-014 | API paper execution requires upstream approvals and idempotency | `/execute` needs typed approvals; duplicates return 409 |
| ADR-015 | Paper writes serialize on a transaction-scoped advisory lock | API/worker/runner cannot lose each other's updates; busy writer -> 503 |
| ADR-017 | Compose bootstrap is shared by `init.sql` and Alembic | Fresh volumes stamp 0001 and apply 0002–0005; one migration head |
| ADR-019 | Strategy drafts reuse `strategies`; lifecycle fields stay server-owned | Authenticated drafts save/load; status, live enablement, and promotion counters reject writes and stay gated |
| ADR-020 | Chat is stateless, read-only, and client-held | Multi-turn history is sent per request; no tools or execution path; exhausted chain -> 503 |

## Models, safety, and operations

| ADR | Decision | Consequence |
|---|---|---|
| ADR-007 | The model roster has a universal fallback | Exhausted chains reach `openrouter/free`; failure never approves a trade |
| ADR-009 | Auth is fail-closed and mounted at one choke point | Every non-public router has `verify_auth`; default key -> 503 |
| ADR-010 | The kill switch latches closed and requires human re-arm | A restart does not silently re-enable trading |
| ADR-011 | Live trading is opt-in at every layer | Default off; human approval and promotion gate before autonomous mode |
| ADR-013 | Production safety is an explicit Compose overlay | `ENVIRONMENT=production` rejects default API/JWT/DB secrets |
| ADR-018 | Dashboard preferences are durable; safety limits stay read-only | `app_settings` persists non-safety preferences; `PUT /settings` cannot raise a cap or threshold |

## Role authorization

| ADR | Decision | Consequence |
|---|---|---|
| ADR-016 | Roles are credential claims; live controls do not depend on the database | JWT carries the role; `/live/kill` works during a DB outage |

## How to add a decision

1. Append a numbered `## ADR-0NN — title` section to `04-DECISIONS.md` with
   context, decision, consequences, and status.
2. Add one row to the matching table above.
3. If the decision changes a folder's job, update its `CONTEXT.md`.
4. If it changes verified state, update `02-STATUS.md`.

## Read next

- Full ADR text: `04-DECISIONS.md`
- Architecture: `03-ARCHITECTURE.md`
- Hard rules: `01-SPEC.md`
