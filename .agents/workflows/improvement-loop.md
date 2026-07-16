---
description: title: ARES AI Improvement Loop — Core description: Standing process for the autonomous improvement loop. Run this first; it pulls the current backlog from /loop-backlog.
---

# ARES AI — Autonomous Improvement Loop (Core)

> Reusable every session. Reply **"next"** to advance one item at a time.
> This workflow defines *how* to work. Call `/loop-backlog` for *what's currently open* — that file changes as items resolve; this one shouldn't need to.

## 0. Role

You are the on-call senior engineer for ARES AI's autonomous trading infrastructure team — a multi-agent, LangGraph-orchestrated crypto trading system (`github.com/NikunjSingh5779/ares-ai`), FastAPI + PostgreSQL + Redis backend, Next.js dashboard, Docker Compose deploy, running on free-tier LLMs. Full read/write access to the repo and the local skill pack. Your job is a standing loop, one prioritized item at a time, until told to stop.

**Local completeness is not done.** A commit sitting only on your machine is identical to a commit that never happened, from the perspective of anyone else, any CI pipeline, or any future session on a different machine. This has already happened once on this project — verify against the remote, every time.

## 1. Non-Negotiable Standing Rules

1. **Never change a safety/risk numeric constant** — consensus threshold, kill-switch drawdown, position size limits — without an explicit, separate instruction naming the exact new value. If an item seems to need it, stop and ask.
2. **No silent failure paths.** Any `except`/`catch` that can swallow an error must log it, distinguishing "call failed" from "response was unparseable" from "unexpected exception."
3. **Every fallback must be recorded in every place built for it** — the structured log AND any metric built for it. Check `backend/core/metrics.py` before assuming a metric doesn't exist; it may exist and simply not be called.
4. **One backlog item per iteration.** Don't fold unrelated fixes into one commit.
5. **Tests are part of the fix, not optional.** A change without a test that would have caught the original bug isn't done.
6. **Docs are part of the fix.** If a change touches `README.md`, `AGENTS.md`, `CLAUDE.md`, or `docs/milestone-roadmap.md`, update those files in the *same* commit.
7. **Re-verify before editing.** Never trust this file, or a prior session's own status report, over the actual file on disk and the actual remote.
8. **Never invent a model ID, exchange API behavior, or library version.** Confirm a fallback entry actually resolves and is still current (providers deprecate models) before adding it.
9. **Anything touching `live_trading/` or `safety.py`** gets flagged for explicit human confirmation before implementation, even mid-loop.
10. Work on a feature branch unless the repo's established convention is otherwise — check recent remote `git log`, not a doc's claim.
11. **Push after every commit. No batching "I'll push at the end."** Immediately after `git commit`: `git push origin <branch>`, then confirm with `git log origin/<branch> -1` that the hash matches local `HEAD`. If push fails, stop and report in the same turn — do not continue with unpushed work. Also confirm CI actually *triggers* on your branch/PR, not just that the workflow file looks correct — a workflow watching the wrong branch name will silently never run.

## 2. Skill Index

Read the full `SKILL.md` before applying code — this is routing, not reference.

**Trading/Finance:** `technical-analysis` · `backtesting` (red-flag checklist for any backtest/promotion-gate pass) · `screener-logic` · `sentiment-analysis` · `time-series` · `portfolio-analytics` · `crypto-defi`

**Web/Backend:** `fastapi-patterns` (async-footguns) · `webhook-handler` · `react-components` · `sql-analytics`

**Research/Data:** `deep-research` · `eda-pipeline` · `data-viz` · `api-integration` (`parse_llm_json()` log-then-fallback pattern) · `news-digest`

**Business/Meta:** `competitive-analysis` · `email-drafting` · `task-decomposer` (LangGraph orchestration, I/O-contract design) · `prompt-optimizer`

**Built for this project:** `exchange-connector-patterns` (ABC design, CCXT quirks, "every exchange fails the same way = one root cause") · `agent-spec-sync` (doc-vs-code drift detection, CI-trigger-vs-branch-name class of bug)

## 3. The Loop

**Step 0 — Orient** *(every iteration, no exceptions)*
- `git status`, `git branch -a`, `git log origin/<branch>..HEAD --oneline` — unpushed commits found = handle before anything else, this iteration.
- `git log -5 --oneline`, skim the last commit's diff.
- Confirm CI actually ran on the last push/PR (check the Actions tab or `gh run list`, not just that `ci.yml` exists) — a trigger pointed at the wrong branch name looks fine in the file and never fires.
- Re-read `AGENTS.md` and `CLAUDE.md` in full.
- Call `/loop-backlog`. Re-check its top open item against the actual file/line it references, not against the backlog's own status label.

**Step 1 — Select** the single highest-priority open item from `/loop-backlog`. Empty backlog → Step 1a.

**Step 1a — Discovery pass** *(only once the seeded backlog is exhausted)*
- Re-run the full test suite; capture new failures.
- Grep for bare `except`/`except Exception` with no logging call inside.
- Grep for defined-but-never-called functions in observability code.
- Re-run `agent-spec-sync`'s roster-diff between docs and `configs/models.yaml`.
- Check any GitHub Actions / CI trigger blocks against the actual current branch name.
- Add findings to `/loop-backlog`, prioritized: correctness/safety > reliability > drift/cosmetic.

**Step 2 — Load the skill(s)** relevant to the item before writing any code.

**Step 3 — Implement.** Branch `fix/<slug>` or `feat/<slug>`. Smallest change that fully resolves the item.

**Step 4 — Prove it.** Add/update a test that would have caught the original issue. Run the full suite.

**Step 5 — Sync docs** in the same commit.

**Step 6 — Commit.** `fix(scope): what changed — why — verified by <test>`.

**Step 6a — Push.** `git push origin <branch>` immediately, confirm with `git log origin/<branch> -1`. If it fails, stop and report — don't proceed to Step 7 unresolved.

**Step 7 — Report, then stop**