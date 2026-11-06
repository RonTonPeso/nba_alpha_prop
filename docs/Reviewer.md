# Code Review Process

Solo development is missing external eyes. This document defines how to get unbiased review at three layers: continuous (CI), per-PR (optional bot), and per-milestone (fresh AI reviewer).

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
- CLAUDE.md (architectural commitments, tech stack, anti-patterns, things to flag)
- docs/PRD.md, section for milestone {MN}
- docs/ROADMAP.md, milestone {MN} (goal, considerations, acceptance criteria)

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

For each milestone in `ROADMAP.md`, add to its acceptance criteria: "Layer 3 review completed; all Blocking findings addressed." This makes review a non-negotiable part of "done."

## Cross-model review for high-stakes milestones

For M3-M4 (backtest infrastructure) and M6 (Bayesian), do two reviews:

1. **Primary:** Fresh claude code or codex session with the template above.
2. **Cross-model:** Paste the same prompt and the same code into GPT-5 (chatgpt.com) or Gemini Advanced. Read both reviews.

When the two reviews agree on a finding, take it seriously. When they disagree, the disagreement itself is informative (one model may be missing context the other has).

You do not need to do cross-model review for every milestone. The cost-benefit tilts only for milestones where a bug would invalidate the project's claims (point-in-time correctness in backtesting; Bayesian model validity).