<!-- AGENTS.md — ARES AI entry catalog. This file routes; it does not hold the spec. -->
# ARES AI — Entry Catalog

Autonomous multi-agent trading platform. LangGraph agents + FastAPI + PostgreSQL /
Redis / ChromaDB, Next.js dashboard, Docker Compose, free-tier LLMs.

**Where am I:** repo root. **Where do I go:** the table below.

Claude Code entry: `CLAUDE.md` is exactly `@AGENTS.md`; there is one source of
truth for project instructions.

## Commands

```powershell
uv sync --locked --all-extras --dev
python -m pytest tests/test_icm_structure.py -q --no-cov   # docs/structure
python -m pytest tests/ -q                                 # full suite
ruff check .; ruff format --check .; mypy .                # quality gates
cd frontend; pnpm install --frozen-lockfile; pnpm build    # dashboard
docker compose --env-file .env -f docker/docker-compose.yml up -d
uv run python scripts/simulate_pipeline.py                 # wiring check
```

## Start here (read in this order)

| Need | File |
|---|---|
| What this project is + every hard rule | `docs/01-SPEC.md` |
| Current verified state and known gaps | `docs/02-STATUS.md` |
| Layers, request flows, MVC map, data ownership | `docs/03-ARCHITECTURE.md` |
| Why the architecture looks like this (ADRs) | `docs/04-DECISIONS.md` |
| What to do next, in order | `docs/05-NEXT.md` |
| Milestone history | `docs/milestone-roadmap.md` |
| Object + process map of the codebase | `docs/map/AGENTS.md` |
| Doc index (ICM + conventional references) | `docs/00-INDEX.md` |
| Product summary / feature status | `docs/PRD.md`, `docs/FEATURES.md` |
| Setup / API / database / deployment | `docs/SETUP.md`, `docs/API.md`, `docs/DATABASE.md`, `docs/DEPLOYMENT.md` |

## Where do I go for task X?

| Task | Read first | Edit |
|---|---|---|
| Agent behavior, prompts, I/O schemas | `agents/CONTEXT.md` | `agents/<agent>.py`, `agents/state.py` |
| API endpoint / request logic | `backend/CONTEXT.md` | `backend/routers/<domain>.py` |
| Paper fills, PnL, portfolio state | `paper_trading/CONTEXT.md` | `paper_trading/*.py` |
| Live orders, safety gates, kill switch | `live_trading/CONTEXT.md` | `live_trading/*.py` |
| Backtest metrics and simulation | `backtesting/CONTEXT.md` | `backtesting/*.py` |
| Model roster, fallback chains | `configs/CONTEXT.md` | `configs/models.yaml` |
| DB schema, migrations, connections | `database/CONTEXT.md` | `database/*.sql`, `migrations/` |
| Dashboard page or component | `frontend/CONTEXT.md` | `frontend/src/app/**`, `frontend/src/components/**` |
| Marketing landing page | `landing/CONTEXT.md` | `landing/src/**` |
| Tests | `tests/CONTEXT.md` | `tests/**` |
| Containers, compose, CI | `docker/CONTEXT.md` | `docker-compose.yml`, `docker/**`, `.github/workflows/**` |
| One-off / operational scripts | `scripts/CONTEXT.md` | `scripts/*.py` |
| ICM docs themselves | `docs/CONTEXT.md` | `docs/**` |

## Hard rules (unchanged — full text in `docs/01-SPEC.md`)

1. Free-tier models only. Model IDs live in `configs/models.yaml`, never in agent source.
2. Every agent input/output is a typed Pydantic schema; `rationale` is required wherever a trading number is produced.
3. **No signal = no trade.** A required agent that fails rejects the trade; it never approves or skips silently.
4. Market Analyst and Quant must both exceed 80% confidence, Risk must approve, and drawdown/exposure must be safe.
5. Live trading starts in human-approval mode. Autonomous mode is opt-in per strategy, only after the paper-trading promotion gate.
6. A kill switch must halt order placement and require human re-arm. Never bypass a safety gate.
7. Never hardcode secrets or commit `.env`. `.env.example` only.
8. Model failure degrades gracefully and is logged with the fallback used.
9. Definition of done: tests pass, `ruff` + `mypy` clean, docs updated in the same change.
10. Never weaken a safety gate to make a test pass.

## Working rules

- Read the routed `CONTEXT.md` and `docs/02-STATUS.md` before editing.
- Surgical changes only: the routed file, files it directly references, and the status line. Say so before widening.
- Run the narrowest test first, then `pytest tests/ -q`, `ruff check .`, `mypy .`.
- No placeholders inside the current milestone. Stub behind a documented interface and flag it.
- Update `docs/02-STATUS.md` (one line) when state changes.
