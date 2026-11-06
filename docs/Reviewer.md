# Code Review Process

Solo development is missing external eyes. This document defines how to get unbiased review at three layers: continuous (CI), per-PR (optional bot), and per-milestone (fresh AI reviewer).

The next review to run is M4, directly below. The general process follows it.

## Current review: M4, plus codebase status

Written 6 Nov 2026 on `m4-calibration`, based on `3abadf1`. Replace this section when the next milestone comes up for review.

### Before you start

1. Commit the M4 work. Right now it is uncommitted and unpushed, so CI has never run on it and a review branch would be empty.
2. Open a fresh session. Do not reuse the one that wrote M4 or this section.
3. Paste the prompt below.
4. M4 calls for a second, cross-model pass. `docs/CLAUDE.md` and `docs/PRD.md` are gitignored, so paste them into that session. A clone does not have them.

### Prompt to paste

````
You are a senior engineer reviewing code for a portfolio project you have not previously seen. Give an honest, thorough, opinionated review. The project forecasts NBA player props and scores those forecasts. Its main promise is that backtests are point-in-time correct.

Read first:
- docs/CLAUDE.md (architectural commitments, anti-patterns, things to flag)
- docs/PRD.md section 6.3 (backtesting infrastructure)
- docs/Roadmap.md, M3 and M4
- The original M4 text, from before this work rewrote it: git show 3abadf1:docs/Roadmap.md

Part 1: M4, in depth.
Scope: everything changed since 3abadf1. That is backend/app/backtest/ (metrics.py, plots.py, quotes.py, run.py), backend/tests/test_calibration.py, backend/tests/test_calibration_db.py, backend/tests/test_baseline_db.py, docs/provenance/m4-calibration.md, and docs/results/m4-*. Use git diff 3abadf1 and include untracked files if the work is not committed yet.

Part 2: the codebase, more lightly.
Read backend/app/models/predict.py, backend/app/db/queries.py, backend/app/scheduler.py, backend/tests/conftest.py, and .github/workflows/ci.yml. Report anything that undermines what M4 claims, or that M5 will inherit.

Form your own view from the code before you read docs/Reviewer.md. Then read its section "Codebase status and measured facts". Those are claims from the session that prepared this review, so reproduce them rather than trusting them, and say if any are wrong. The local Postgres is populated. Query it read-only. Do not run the replay, because it commits rows to predictions. The tests are safe: they run inside a rolled-back transaction.

Answer these directly:
1. M4 changed its own goal, tasks, and acceptance in the same diff as the code. Judge the work against the original text and against the rewrite. Which changes are justified, and which only make the milestone easier to pass?
2. Does any report in docs/results/ lead a reader to a stronger conclusion than the data supports? Follow each headline number back to the rows behind it: which games, which players, and what history was visible.
3. Does each point-in-time rule hold on every path that reaches a score: features, lines, quotes, and outcomes? Is an unfiltered read a leak, or a defensible choice?
4. Do the tests fail if the behavior they name breaks? Which of them actually run in CI?
5. Is the ingested_at design workable for backtesting a period that was bulk loaded later? If not, what decision does the project owe before M5? Name the options and the tradeoffs. Do not implement one.

Also look for:
- Bugs and correctness issues: edge cases, and error paths that fail silently.
- Violations of the three commitments in docs/CLAUDE.md. Lineup-conditional projections and the Bayesian layer are planned for later milestones and are not expected yet. Point-in-time correctness applies now.
- Redundancy and complexity that does not earn its keep.
- Test gaps.
- Security issues.
- Documentation gaps, including major decisions with no ADR and docs that contradict the code.

Classify each finding:
- Blocking: must fix before merging. Correctness bugs, security issues, commitment violations, and claims the data does not support.
- Important: should fix soon. Significant test gaps, meaningful redundancy, design issues that will compound.
- Suggestion: consider for later.

Be specific, with file:line references and the concrete failure. If a category is clean, say so. Do not manufacture findings. Do not write fix code.

Format:

## Summary
(2-3 sentences on overall quality and the most important takeaway)

## Blocking
## Important
## Suggestions
(each with file:line references)

## Answers to the five questions

## Status claims checked
(each one confirmed, wrong, or not checked)

## What's done well
(2-3 specific things, with file references)
````

### Codebase status and measured facts

Measured 6 Nov 2026 against the working tree and the local database, unless a line says otherwise.

| Milestone | State |
| --- | --- |
| M0 skeleton | On `main`. FastAPI with only `GET /health`, Postgres, Alembic, CI. |
| M1 NBA ingestion | On `main`. |
| M2 Kalshi ingestion | On `main`. The snapshot job has never run live. ADR-3 still says "Ronnie to rewrite in his voice". |
| M3 baseline and replay | Merged in PR #3. "Hit rate beats 50% on a held-out month" is still unmet. |
| M4 calibration | Uncommitted on `m4-calibration`. Under review here. |
| M5 to M10 | Not started. No XGBoost, PyMC, injury pipeline, lineup model, or alerts. The frontend is a placeholder page. |

Quality gates on the working tree: ruff, black, and mypy are clean. pytest gives 91 passed with Postgres up.

Data in the local database, at Alembic revision `c3b1a9e0d4f2`:

| Table | Contents |
| --- | --- |
| `games` | 5,279, from 2022-10-18 to 2026-06-13 |
| `player_game_logs` | 112,884, no duplicate player-game pairs |
| `markets` | 19,736, all resolved to a player and a game, 148 players |
| `market_settlements` | 18,822 |
| `market_snapshots` | 0 |
| `predictions` | 168, all `baseline-m3-v1`, all from the June replay |

When the box scores were ingested, which is what the point-in-time filter sees:

| Ingested | Rows | Covers |
| --- | --- | --- |
| 2026-05-31 | 78,602 | Regular season, 2022-10-18 to 2025-04-13 |
| 2026-06-05 21:13 UTC | 26,651 | Regular season, 2025-10-21 to 2026-04-12 |
| 2026-06-15 | 7,631 | All Play-In and playoff games, 2023 to 2026-06-13 |

Contracts by game month:

| Month | Contracts | Games | Players |
| --- | --- | --- | --- |
| 2026-03 | 4,138 | 55 | 124 |
| 2026-04 | 11,492 | 143 | 142 |
| 2026-05 | 3,998 | 38 | 66 |
| 2026-06 | 108 | 1 | 10 |

Deploys and data flow: the Vercel placeholder returned 200 and the Railway health URL returned 404. The scheduler is off, so nothing is collecting box scores or quotes during the current season.

**Facts that conflict with the M4 write-up or limit what it shows:**

1. **Every scored contract comes from one game.** The June report covers five games, but only `0042500401` (2026-06-03) has markets: 108 contracts on 10 players, 105 of them scored. Brier, log loss, hit rate, and the reliability table all rest on that one night. Neither the report nor `docs/provenance/m4-calibration.md:88-90` says so.
2. **That game was forecast from history that ended 14 months earlier.** The 2025-26 season was not ingested until 2026-06-05, so the last visible game at the 3 June clock is 2025-04-13. Median stored `rest_days` is 418, and those players go through the rested branch of the rest adjustment. The provenance describes this history as "mostly the regular season". The 2026-06-05 game has the same problem, because its clock falls before the 21:13 UTC load. Those two forecasts follow the filter correctly, but they say little about how the baseline would do with current data.
3. **November 2025 has no contracts in this database.** The earliest game month is March 2026. `docs/provenance/m4-calibration.md:86` says "Kalshi coverage exists in that month", and the M4 report for a real month is that November window. Fixing `ingested_at` alone would not populate it. April 2026 is the first full month with lines. The bulk load was asked for closes from 2025-11-01, and why nothing before late March came back is unexplained.
4. **No real month has been scored.** Every game outside June 2026 fails the clock, because all of its box scores were loaded afterward. The roadmap rewrite accepts an empty report as meeting "a real month".
5. **The market comparison has never seen a real quote.** `market_snapshots` is empty, so `latest_yes_mid` and the disagreement count have only run on test fixtures.
6. **Markets have no clock in the replay.** `backend/app/backtest/run.py:135` and `backend/app/models/predict.py:227` read `Market` with no time filter. Every market's `ingested_at` is 2026-06-10 or later, and 806 of 19,736 contracts opened after their game's 16:00 UTC clock. None of the 806 are in the scored game. Prices are filtered and strikes are not.
7. **The report says "stored", but the replay recomputes.** The report says the probability comes from "the normal stored on the prediction". `run.py:115` uses the forecast `predict_player_game` just computed and never reads `Prediction`. Changing the model without bumping its version would change the scores while the stored rows stay as they were.
8. **The weak reference point flatters the score.** The provenance compares Brier 0.178 to 0.25 for a constant 0.5. On the report's own bins, 38 of 105 contracts resolved yes. A constant at that base rate scores about 0.231 (in-sample), and always betting under hits 67/105 = 0.638 against the reported 0.695. Contracts on one player's strike ladder in one game are heavily correlated, and the report gives no interval.
9. **CI does not run any database test.** The workflow has no Postgres service. With the database unreachable, the suite gives 42 passed and 49 skipped, and the skips include all of `test_point_in_time.py` (6), `test_baseline_db.py` (4), and `test_calibration_db.py` (4). The green CI on PR #3 did not exercise the leak tests. The M4 smoke test builds its summary by hand and never calls `replay`.
10. **The live prediction job looks unable to produce rows.** This comes from reading the code. It has not been run. `run_daily_predictions` selects games dated today (`predict.py:248`), but `Game` rows are only written from `LeagueGameLog` (`backend/app/data/nba.py:244`), which is post-game data. No schedule source exists, and no test calls the function.
11. **Two settlements disagree with the box score.** 2 of 18,822, both rebounds: `KXNBAREB-26APR26SASPOR-SASVWEMBANYAMA1-12` and `KXNBAREB-26APR18ATLNYK-ATLOOKONGWU17-8` settled no with the box score above the line. The cause is unknown. The replay scores against the box score, not the settlement.

**Docs that no longer match the code:**

- `README.md` and `docs/status.md` say M2 is unmerged and the model and backtest packages are empty.
- `docs/adr.md:3` says ADR-3 is not merged.
- `docs/next-session.md` describes an overnight plan that was overtaken by M3.
- `.cursor/rules/provenance.mdc` lists `Roadmap.md`, `process.md`, and `Reviewer.md` as gitignored. They are tracked, and the repo is public.
- `backend/app/db/tables.py:23` says markets carry `created_at` only. They also have `ingested_at`.
- `backend/app/data/kalshi_player_aliases.csv` is gitignored, so alias seeding cannot be reproduced from a clone.

**Not verified:** the frontend build (no M4 change touches it), a live call to either upstream API, and whether the two settlement mismatches come from stat corrections.

**To reproduce the database facts** (read-only):

```bash
docker exec -i nba_alpha_prop-postgres-1 psql -U nba -d nba_alpha_prop -At -F ' | ' <<'SQL'
BEGIN READ ONLY;
-- Contracts by game month (facts 1 and 3)
SELECT to_char(g.game_date,'YYYY-MM'), count(*), count(DISTINCT m.game_id), count(DISTINCT m.player_id)
FROM markets m JOIN games g ON g.game_id = m.game_id GROUP BY 1 ORDER BY 1;
-- Stored rest days by game in the June window (fact 2)
SELECT g.game_date, count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY (p.payload->>'rest_days')::int)
FROM predictions p JOIN games g ON g.game_id = p.game_id GROUP BY 1 ORDER BY 1;
-- Last game visible at the 3 June clock (fact 2)
SELECT max(lg.game_date), count(DISTINCT l.player_id)
FROM player_game_logs l JOIN games lg ON lg.game_id = l.game_id
WHERE l.player_id IN (SELECT player_id FROM markets WHERE game_id = '0042500401')
  AND l.event_time < '2026-06-03 16:00+00' AND l.ingested_at <= '2026-06-03 16:00+00';
-- Snapshot count (fact 5)
SELECT count(*) FROM market_snapshots;
-- Contracts opened after their clock (fact 6)
SELECT count(*) FILTER (WHERE m.open_time > (g.game_date + time '16:00') AT TIME ZONE 'UTC'), count(*)
FROM markets m JOIN games g ON g.game_id = m.game_id;
ROLLBACK;
SQL
```

To reproduce fact 9, from `backend/`:

```bash
DATABASE_URL='postgresql+psycopg://nobody:nobody@127.0.0.1:1/none' uv run pytest -q
```

## Why this matters

The AI that writes code has lived through the design decisions. It has confirmation bias about its own choices. A reviewer fresh to the code does not share that bias because the bias lives in the context window, not the model weights. Resetting context removes it.

This document codifies how to use that property deliberately.

## Three review layers

### Layer 1: Continuous (every push)

Already running in CI:
- `ruff` for linting
- `black --check` for formatting
- `mypy` for type checking
- `pytest` for tests

This catches mechanical issues automatically. No action needed beyond keeping CI green.

### Layer 2: Per-PR (optional)

A GitHub PR bot reviewing every PR. Recommended tools:
- **CodeRabbit** (free tier exists, generous for solo projects)
- **Greptile** (free for open-source repos)
- **Bito**

Set this up once, run forever. The review comments end up on PRs, which recruiters see when browsing the project.

This is optional. Decision: set up CodeRabbit after M2 (gives some real code for the bot to comment on first).

### Layer 3: Per-milestone (the important one)

A fresh AI session reviews the milestone's code before merging to main. This is the highest-leverage review because it catches design and architectural issues that automated tools miss.

The workflow:

1. **Finish the milestone.** All tasks done. CI green. PRD acceptance criteria checked off.
2. **Push to a review branch:** `git checkout -b review/M3-baseline-model && git push -u origin review/M3-baseline-model`
3. **Open a fresh claude code or codex session.** This is non-negotiable. Close the session that wrote the code. Start a new one. The freshness is what removes the bias.
4. **Paste the reviewer prompt** (template below) with the milestone number and scope filled in.
5. **Receive the review.** Findings are categorized by severity (Blocking, Important, Suggestion).
6. **Address blocking findings.** File GitHub issues for Important and Suggestion findings, link them to the milestone, address Important ones soon, Suggestions when convenient.
7. **Merge to main** when blocking findings are resolved and CI is green.

For higher-stakes milestones (M3-M4 backtest infra, M6 Bayesian), do a **cross-model review** as a second pass: paste the code into GPT or Gemini's web UI with the same reviewer prompt. Different models have different blind spots; the second perspective catches what the first rationalizes.

## The reviewer prompt template

Copy this. Fill in `{MN}`, milestone name, and scope before pasting into a fresh session.

````
You are a senior engineer reviewing code for a portfolio project you have not previously seen. Your job is to provide an honest, thorough, opinionated review.

Read these documents first to understand the project's commitments and acceptance criteria:
- docs/CLAUDE.md (architectural commitments, tech stack, anti-patterns, things to flag)
- docs/PRD.md, section for milestone {MN}
- docs/Roadmap.md, milestone {MN} (goal, considerations, acceptance criteria)

Now review the code in: {scope}

(For example: backend/app/models/ and backend/app/backtest/, or the diff since git tag M2-complete.)

Your review should look for:

1. **Bugs and correctness issues** - logic that doesn't work as intended, edge cases not handled, error paths that fail silently.
2. **Violations of architectural commitments** - particularly the three core commitments in CLAUDE.md:
   - Point-in-time correctness in backtesting (no future-info leakage)
   - Lineup-conditional projections (injuries flow through lineup layer, not as a hard penalty)
   - Hierarchical Bayesian model wrapping XGBoost (both layers present and integrated correctly)
3. **Redundancy** - duplicated logic, code that does the same thing in multiple places, helpers that already exist.
4. **Unnecessary complexity** - abstractions that don't earn their keep, premature optimization, over-engineering, indirection that hides simple logic.
5. **Test gaps** - logic that should be tested but isn't, especially around the architectural commitments. Specifically look for whether point-in-time correctness has a regression test.
6. **Security issues** - hardcoded secrets, unsafe data handling, missing input validation, dependencies with known vulnerabilities.
7. **Documentation gaps** - non-obvious decisions without explanation. Major design choices without an ADR.

For each finding, classify severity:
- **Blocking**: must fix before merging. Bugs that affect correctness, security issues, violations of architectural commitments.
- **Important**: should fix soon. Significant test gaps, meaningful redundancy, design issues that will compound.
- **Suggestion**: consider for later. Minor style issues, optional improvements, opinions where reasonable people might disagree.

Be specific. Don't say "consider improving error handling." Say "in backend/app/data/kalshi.py line 47, the bare `except:` clause swallows all exceptions including KeyboardInterrupt, which means Ctrl-C won't stop the script."

Be honest. If the code is good, say so. Don't manufacture findings to seem thorough. If you find no issues in a category, say so explicitly.

Do not write fix code. Identify issues and explain them. Implementing fixes is the developer's job; the value of the review is in identifying things they would not have noticed.

Format your output as:

## Summary
(2-3 sentences on overall quality and the most important takeaway)

## Blocking
(list with file:line references)

## Important
(list with file:line references)

## Suggestions
(list with file:line references)

## What's done well
(2-3 specific things, with file references)
````

## What this process is not

A few things to keep in mind to avoid this becoming theater:

- **It is not a substitute for understanding your own code.** If a reviewer flags something and you don't understand why, dig in until you do. Don't fix it by pattern-matching on the suggestion.
- **It is not infallible.** The reviewer can be wrong. If a finding seems off, push back. Disagreement with a reviewer is fine; the conversation usually surfaces the real issue (which may be that your code needs comments explaining intent, not that the code itself is wrong).
- **It is not for replacing tests.** The reviewer catches issues; tests prevent regressions. Both are needed.
- **It is not free.** A milestone review takes 30-60 minutes including reading findings and addressing them. Budget that in the milestone effort.

## Per-milestone severity expectations

A rough sense of what to expect:

- **M0 (skeleton):** Few findings, mostly suggestions. The code is mostly framework boilerplate.
- **M1-M2 (ingestion):** A handful of findings around error handling, retry logic, cache correctness. Some Important findings likely.
- **M3-M4 (model + backtest):** This is where point-in-time correctness gets tested for real. Expect Blocking findings if anything is subtly leaking.
- **M5 (XGBoost):** Feature engineering tends to accumulate dead code and redundancy. Expect Important findings on this.
- **M6 (Bayesian):** Highest-stakes review. Cross-model review recommended. Look for prior choices that don't match domain knowledge, hierarchical structure that may not converge, sampling pitfalls.
- **M7 (injury LLM + lineup):** Watch for LLM prompt sensitivity, source-reliability assumptions, lineup model that doesn't validate against historical data.
- **M8-M9 (dashboard + alerts):** Mostly Suggestions. The risk here is UX and copy, less so correctness.
- **M10 (polish):** A final security audit pass plus README quality review.

If a milestone returns *zero* blocking findings on the first review, either the milestone was simple (M0, M8, M9 are candidates) or the reviewer wasn't doing its job. Re-prompt with more pressure on a specific category if needed.

## Integration with the roadmap

For each milestone in `docs/Roadmap.md`, add to its acceptance criteria: "Layer 3 review completed; all Blocking findings addressed." This makes review a non-negotiable part of "done."

## Cross-model review for high-stakes milestones

For M3-M4 (backtest infrastructure) and M6 (Bayesian), do two reviews:

1. **Primary:** Fresh claude code or codex session with the template above.
2. **Cross-model:** Paste the same prompt and the same code into GPT-5 (chatgpt.com) or Gemini Advanced. Read both reviews.

When the two reviews agree on a finding, take it seriously. When they disagree, the disagreement itself is informative (one model may be missing context the other has).

You do not need to do cross-model review for every milestone. The cost-benefit tilts only for milestones where a bug would invalidate the project's claims (point-in-time correctness in backtesting; Bayesian model validity).