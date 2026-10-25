<!-- docs/map/AGENTS.md -->
# System map — how to use

The map answers two questions a cold agent cannot answer from a file tree:

1. **What is X?** → open the object card.
2. **What else moves if I change X?** → read the card’s *Change impact* section.

Cards are one page each. They name the home file, the readers/writers, invariants, and
the tests that catch a break. They do not duplicate code.

## Objects (nouns)

| Object | Card | Home |
|---|---|---|
| Agent state and every agent output | `objects/agent-state.md` | `agents/state.py` |
| Portfolio, position, order, paper record | `objects/portfolio.md` | `paper_trading/engine.py`, `repository.py`, `ledger.py`, DB tables |
| Model roster, fallback chain, breaker | `objects/model-roster.md` | `configs/models.yaml`, `agents/router.py` |
| Dashboard preferences | `objects/app-settings.md` | `app_settings` row, `backend/services/settings_service.py` |
| Strategy drafts | `objects/strategy.md` | `strategies` table, `backend/services/strategy_service.py` |

## Processes (movements)

| Process | Card | Trigger |
|---|---|---|
| Analysis pipeline | `processes/analysis-pipeline.md` | `/api/v1/analyze`, `/signal`, SSE |
| Execution and promotion | `processes/execution.md` | `/execute`, `/live/*`, runner loop |
| Self-improvement | `processes/self-improvement.md` | post-run hook after memory/log, `/agents/improvements` |

## Rules

- A card is updated **in the same change** as its object or process.
- If a card and the code disagree, the code is right; fix the card.
- Known defects are listed under *Known gaps* and summarised in `docs/02-STATUS.md`.
