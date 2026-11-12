# Roadmap

A living document. Update it when reality diverges from the plan, which it will.

## How to use this document

This is a guide, not a contract. Three rules for keeping it useful:

1. **Edit it.** When something changes (scope shifts, a milestone reveals it's harder than expected, a tool gets swapped), update this file in the same commit. A stale roadmap is worse than no roadmap.
2. **Read the current milestone before each work session.** Five minutes at the start to re-orient. Skip the milestones you have already shipped.
3. **Treat effort estimates as guesses.** They're here to set rough expectations, not to bind you. The Bayesian milestone is going to take longer than you think; the others may take less.

The roadmap has eleven milestones (M0 through M10). Each has:
- A goal (what success looks like)
- Tasks (concrete things to build)
- Considerations (things to think about while building)
- Branch points (decision moments where you may diverge from the default)
- Acceptance (when to call the milestone done)
- Rough effort estimate

For acceptance criteria of specific features, see `docs/PRD.md`. For the project's architectural commitments and tech stack, see `docs/CLAUDE.md`. For schema and ADR-level decisions, see `docs/adr.md`. This roadmap is the temporal sequence; those are the spec.

## A realistic look at total effort

Best estimate: 200-300 hours of focused work across all milestones. At 8-12 hours/week, that translates to roughly 20-30 weeks (5-7 months) from M0 to M10. The PRD's earlier 8-12 week estimate was optimistic; this is the honest version. If life gets in the way for a few weeks at a time, expect 6-9 months calendar time.

## Pre-flight checklist (before M0)

Mostly done; left as a record of what setup looked like.

- [x] GitHub repo created (public, MIT licensed)
- [x] Repo cloned locally
- [x] `docs/CLAUDE.md` (moved here from repo root)
- [x] `docs/PRD.md`
- [x] `docs/Roadmap.md` (this file)
- [x] `~/.claude/CLAUDE.md` with global working preferences
- [x] `.gitignore` at root
- [x] `.env.example` at root
- [x] Local `.env` with `ANTHROPIC_API_KEY`, gitignored
- [x] Anthropic API budget cap set
- [x] Python 3.11+ installed
- [x] Node 18+ installed
- [x] Docker Desktop installed
- [x] `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [x] Claude Code installed and authenticated
- [ ] McElreath's *Statistical Rethinking* obtained (book or free lectures); start chapter 1 this week regardless of which milestone you're on

---

## M0: Setup & Skeleton

**Status:** Done (2026-05-15). Backend at Railway, frontend at Vercel, CI on every PR, health check live.

**Effort:** ~10-15 hours

**Goal:** Repo skeleton is live. Backend and frontend exist as empty shells. Postgres runs locally in Docker. CI runs on every PR. Health check is reachable from a Railway URL and a Vercel URL.

There are no features yet. That is the point. Getting deployment unblocked early prevents it from being a panic later.

**Tasks:**
- Backend skeleton: `pyproject.toml` via `uv init`, FastAPI app with `/health` endpoint, basic project structure matching CLAUDE.md's repo layout
- Dockerfile at `backend/`
- `docker-compose.yml` at repo root with Postgres service
- Alembic initialized (no migrations yet, just the scaffolding)
- Frontend skeleton: Next.js + TypeScript + Tailwind + TanStack Query installed, one empty page
- Pre-commit hooks via `.pre-commit-config.yaml`: ruff, black, mypy
- GitHub Actions workflow at `.github/workflows/ci.yml`: runs pytest, ruff, mypy, plus frontend lint on every PR
- Deploy backend to Railway (just the `/health` endpoint)
- Deploy frontend to Vercel (just the empty Next.js page)
- README placeholder explaining the project is under construction

**Considerations:**
- Resist the urge to add anything else. The point of M0 is the skeleton.
- The first Claude Code session lives here. Use it to set up the skeleton, not to write business logic. Walk through every generated file.
- Test that hot reload works locally for both backend (uvicorn `--reload`) and frontend (`next dev`).
- Confirm CI is actually running on PRs by opening a tiny PR (add a comment to a file) and watching the checks.

**Branch points:**
- *Sentry now or post-v1?* Default: post-v1. Skip during M0.
- *Branch protection on main now or later?* Default: now. Cheap to set up, free signal of discipline.
- *Single repo or split frontend/backend repos?* Default: single repo (monorepo-ish). Easier to coordinate, easier for recruiters to see the whole thing.

**Acceptance:**
- `docker compose up -d` brings up Postgres locally
- `uv run uvicorn app.main:app --reload` runs the backend locally
- `npm run dev` runs the frontend locally
- Visiting Railway URL returns 200 from `/health`
- Visiting Vercel URL renders the bare Next.js page
- A test PR triggers CI and CI passes

---

## M1: NBA Data Ingestion + Schema Foundation

**Status:** Done (2026-05-30). Six tables live with strict point-in-time correctness, `CachedHttpClient` over `curl_cffi` (chrome120 fingerprint) wrapping a Postgres-backed `request_cache`, bulk historical loader for 2022-23 onward via `LeagueGameLog` (one call per season per PlayerOrTeam value), daily ingest job for new games, four failure-mode tests (timeout, 429, malformed JSON, missing field), spot-check helper. The Bulk load was extended in M2 to also cover `Playoffs` and `PlayIn` season types when Kalshi market data revealed those games were needed for FK resolution.

**Branch points hit:**
- Used `curl_cffi` instead of httpx for `stats.nba.com` because httpx's TLS fingerprint was triggering 403s even with browser-like headers. Same wrapper interface, different transport; no callers cared.
- Stuck with the default 2022-23 start window; no need to go back further yet.
- SQLModel chosen over raw SQLAlchemy as planned.

**Effort:** ~20-30 hours

**Goal:** Historical NBA box scores are in Postgres with strict point-in-time correctness. A daily job pulls new games during the season. The schema design has an ADR explaining the choices.

**Tasks:**
- Database schema: six tables. Fact tables (`games`, `game_results`, `player_game_logs`) carry both `event_time` and `ingested_at`. Identity tables (`players`, `teams`) carry `created_at`. Infrastructure: `request_cache`.
- ADR at `docs/adr.md` explaining the schema and why point-in-time correctness flows through it
- Alembic migrations creating the schema
- Postgres-backed `request_cache` plus a `CachedHttpClient` wrapper around httpx, so every outbound call is keyed, cached, and replay-safe
- Bulk historical load script using the `LeagueGameLog` endpoint at `https://stats.nba.com/stats/leaguegamelog`. Two calls per season: `PlayerOrTeam=P` for `player_game_logs` + player identity, `PlayerOrTeam=T` for `games`, `game_results`, team identity. 2022-23 onward. No `nba_api` Python library dependency; we hit the endpoint directly through the cached wrapper with browser-like headers.
- Daily ingestion job uses the same `LeagueGameLog` endpoint with `DateFrom`/`DateTo` set to yesterday. Same parser code path as the bulk load.
- Tests covering the ingestion happy path plus four specific failure modes: httpx timeout, 429 rate limit, malformed JSON, missing field (upstream schema drift)
- Spot-check helper that prints three random games' box scores so they can be eyeballed against basketball-reference.com before the bulk load is declared trustworthy

**Considerations:**
- Players get traded, retire, have name changes. Store a stable `player_id` (NBA's official ID) and put `team_id` on the game log, not on the player record.
- The schema is foundational. Get it right. Spend extra time here; it pays off later.
- `stats.nba.com` rate-limits aggressively and returns 403 without browser-like headers. `CachedHttpClient` does the fetch once, stores the JSON in `request_cache`, and serves repeats from Postgres. Without that wrapper the bulk load is fragile.
- Bulk historical play-by-play (shufinskiy / pbpstats) is deferred to M7 when lineup features need it. Shufinskiy was investigated in `notebooks/explore_shuf.ipynb`; takeaway was that it's raw events, not box scores, so it's the wrong source for `player_game_logs`.
- The franchise / temporal-identity split was considered and rejected. Major NBA renames are pre-2014; our 2022-23+ window doesn't cross any. A single `teams` table keyed by NBA's team ID covers everything.
- Don't try to ingest everything. 2022-23 onward is plenty. Backfill more later if needed.

**Branch points:**
- *How far back to load?* Default: 2022-23 season. Going back to 2018-19 doubles storage but provides more training data. Defer to M5 if needed.
- *Normalize via foreign keys or denormalize?* Default: normalize. Postgres is fast enough.
- *Use SQLModel or raw SQLAlchemy?* Default: SQLModel. The Pydantic integration is nice for FastAPI responses.

**Acceptance:**
- `SELECT * FROM player_game_logs WHERE player_id = X AND event_time < Y AND ingested_at <= Y` returns correct point-in-time results
- The point-in-time regression test (`backend/tests/test_point_in_time.py`) passes locally and forces callers to pass `as_of` explicitly via a keyword-only argument
- Daily job runs and adds new games without re-fetching existing
- Three random games' box scores from the loaded data have been manually compared against basketball-reference.com and match
- Tests pass in CI (DB-backed tests skip gracefully if Postgres isn't available; the unit-style tests still run)

---

## M2: Kalshi Market Data Ingestion

**Status:** Done (2026-06-15). Four tables (`markets`, `market_snapshots`, `market_settlements`, `kalshi_player_aliases`) live with the same point-in-time pattern as M1. Bulk historical loader brought in 19,736 settled markets across the three series (`KXNBAPTS`, `KXNBAREB`, `KXNBAAST`). 5-min snapshot job for active markets wired into the scheduler alongside the daily NBA ingest, both gated by `SCHEDULER_ENABLED`. Four failure-mode tests cover the Kalshi source (timeout, 429, malformed JSON, missing field). Three settled markets spot-checked against kalshi.com.

**Branch points hit:**
- REST polling at 5-min cadence chosen as planned (no WebSocket, no orderbook).
- All four price legs stored (yes_bid, yes_ask, no_bid, no_ask) per the ADR; cheap to store and avoids re-fetching to compute alternates.
- Composite PK `(ticker, quoted_at)` on `market_snapshots`; gives idempotency and a natural btree for the snapshot-closest-to-T query.
- No separate `kalshi_game_aliases` table; M1's `Game.game_date` joined directly via Kalshi's team abbreviations.
- 429 retry-with-backoff added to `CachedHttpClient` after the live Kalshi public endpoint rate-limited mid-pull. Independent of the existing timeout retry path.
- Discovered Kalshi's playoff prop coverage required loading NBA playoff and Play-In games into M1's schema. M1's `bulk_load` CLI choices extended from `["Regular Season", "Playoffs"]` to `["Regular Season", "Playoffs", "PlayIn"]`; playoffs and Play-In loaded across four seasons. Game FK resolution went from 53% to 100% over those passes.

**Effort:** ~15-20 hours

**Goal:** Kalshi NBA prop markets are snapshotted every 5 minutes during game days. Historical settled markets are loaded once for backtest use.

**Tasks:**
- Schema: `markets`, `market_snapshots` (bid, ask, last, volume, `quoted_at`), `market_settlements`
- Kalshi REST API client using httpx async
- Snapshot job that runs every 5 minutes when games are upcoming
- Historical backfill from Kalshi's settled-markets endpoint
- Parser that maps Kalshi's market identifiers to (player, prop_type, game) tuples in your schema
- Tests

**Considerations:**
- Kalshi market identifiers may not be obvious. Spend time understanding their naming conventions before writing the parser.
- The snapshot job should be cheap. 5-min cadence × ~50 players × ~3 prop types × game hours is manageable, but don't be reckless.
- Store all four price fields (bid, ask, last, volume). Even if you only use mid-price in v1, having the full picture lets you reason about spread costs and liquidity later.

**Branch points:**
- *WebSocket for real-time or REST polling?* Default: REST polling. PRD says no real-time for v1. Stick with that.
- *5-min cadence or different?* Default: 5 min. Tune later based on observed price movement.
- *Should you also store the orderbook?* Default: no. Top-of-book is enough for v1.

**Acceptance:**
- Live Kalshi NBA prop markets are captured at 5-min intervals during games
- Historical settled markets loaded for at least the 2025-26 season
- Can query market price for player X, prop Y, at time T and get the snapshot closest to (but not after) T

---

## M3: Baseline Model + Skeleton Backtest Harness

**Status:** Merged (PR #3, 2026-11-06). Baseline, `predictions` table, 16:00 UTC job, and `python -m app.backtest.run` are on main. Design notes are in `docs/provenance/m3-baseline.md`. Hit rate above 50% on a held-out month is still not claimed. The markets loaded in this database begin on 2026-03-25, and bulk-loaded `ingested_at` values sit on the fetch day, so a 2025 replay that keeps the point-in-time filter will not see those rows.

**Effort:** ~15-20 hours

**Goal:** An end-to-end pipeline works: predictions are generated, stored with timestamps, and a backtest replays them against historical outcomes. The model itself is intentionally dumb. The point is to validate the infrastructure.

**Tasks:**
- `predictions` table schema with `prediction_time`, `model_version`, full prediction payload
- Simple baseline model: rolling average over last 15 games, with home/away and rest-day adjustments
- Daily prediction job that produces predictions for all upcoming games' player-props
- Skeleton backtest harness: replay predictions day by day, compare to outcomes
- Basic metrics: hit rate (predicted-over vs actual-over), mean absolute error

**Considerations:**
- The baseline being dumb is not a bug. Its job is to expose pipeline issues, not to make money.
- The backtest harness designed here is the same one M4 extends. Design it for replay, not for one-shot evaluation.
- Write the point-in-time correctness regression test now: a test that tries to make a prediction using future data and confirms it fails loudly.

**Branch points:**
- *Skip baseline, go straight to XGBoost?* Default: do not skip. The baseline catches bugs in ingestion and pipeline layers that would be much harder to debug under a complex model.
- *Predict for all players or only Kalshi-covered ones?* Default: only Kalshi-covered players (~50). Reduces compute, matches the market scope.

**Acceptance:**
- Predictions are stored with correct point-in-time timestamps
- `python -m app.backtest.run --start 2025-01-01 --end 2025-01-31` produces a report
- Baseline's hit rate beats 50% on a held-out month (it should; even rolling averages are not random)
- Point-in-time regression test passes

---

## M4: Backtest Harness with Calibration Metrics

**Status:** In progress (2026-11-06), branch `m4-calibration`. The revisions below are written up in `docs/provenance/m4-calibration.md`.

**Effort:** ~10-15 hours

**Goal:** The same replay scores the baseline as a probability: Brier score, log loss, a reliability diagram, and a count of disagreements with the pre-tip yes mid.

**Tasks:**
- Brier score and log loss, with unit tests against hand-computed values
- Ten equal-width probability bins, a markdown table, and an SVG reliability diagram
- Disagreement count against the yes mid, only when a snapshot is visible at 16:00 UTC
- Markdown report in `docs/results/`
- CI smoke test on a synthetic week (5 players, 7 days, one contract each) inside the existing pytest job

**Considerations:**
- Implement metrics with synthetic test data first. Compute Brier on a fake dataset with known properties and confirm the answer matches the hand-computed value. This is the only way to be sure the metric implementation is correct.
- Reports are the most useful artifact of this milestone. Make them readable. A recruiter clicking through `docs/results/` should be able to tell a synthetic fixture from a real month.
- The stored forecast is a normal mean and std. The probability is that normal's upper tail at the line. It is not a posterior.

**Branch points:**
- *Build the calibration view in the dashboard now or in M8?* M8. This milestone writes the table and the SVG. The dashboard renders later.
- *How granular should calibration buckets be?* Ten equal-width bins on [0, 1], not equal-count deciles. Chosen 2026-11-06. The baseline piles up near one probability, and equal-count bins would look calibrated because of how they are cut. Empty bins stay in the table.
- *Score predicted edge against realized return?* Not in this milestone. Chosen 2026-11-06. The project does not book trades. The report counts how often the side priced above the quoted mid happened. No payout, no expected value.
- *Fail CI when a one-week sample is miscalibrated?* No. Chosen 2026-11-06. Five players over seven days is too small for that gate, and CI does not load the season. The smoke test locks the synthetic Brier score. A large calibration error is printed in the report and does not fail the job.

**Acceptance:**
- Metrics produce correct values on synthetic test data
- A backtest report exists in `docs/results/` for a real month, including the case where the point-in-time filter leaves the probability section empty
- CI smoke test runs and passes

---

## M5: XGBoost Feature Predictor

**Status:** Fit on 2026-11-07, `uv run python -m app.models.fit`. Holdout starts 2025-12-05 (last 20% of game dates). Headline rest is 14 days or less: 993 games, XGBoost MAE 2.627 against baseline 2.776 on 62,271 player-props. The same direction holds for points (4.603 vs 4.889), rebounds (1.920 vs 2.021), and assists (1.358 vs 1.419). Residual Brier 0.159651 against baseline 0.168920 on 18,878 contracts. The report is `docs/results/m5-xgb.md`. The note is `docs/provenance/m5-xgb.md`. The scheduler was not wired.

**Effort:** ~25-35 hours after the clock decision. A strict-clock pass is a short refusal report, not a model.

**Goal:** A second point predictor, one XGBoost model per prop, trained only on rows the same 16:00 UTC clocks can see. The baseline keeps running. The milestone is the comparison.

**Tasks:**
- Ten features, all computed from prior box scores visible at the prediction clock:
  - Points mean, last 5 games and last 15
  - Rebounds mean, last 15
  - Assists mean, last 15
  - Minutes mean, last 15
  - Home or away, from the previous visible game's team
  - Rest days, capped at 14
  - Box-score usage proxy over the last 15: field-goal attempts + 0.44 * free-throw attempts + turnovers, divided by the same sum for teammates in those games
  - Opponent points allowed, mean of the opponent's last 15 visible games
  - Days since the player's last 30-point game, capped at 60
- One booster per prop (`points`, `rebounds`, `assists`). Fixed hyperparameters on the first fit.
- Date holdout: sort by `game_date`, train on earlier dates, score the last held-out dates. Same-night rows stay in one side of the split.
- Residual standard deviation from the training rows only, so the stored row still has a normal band and M4 can score Brier. The band is a residual, not a posterior.
- SHAP values for the top 5 features, stored on the prediction payload.
- `model_version` `xgb-m5-v1` on every row. `baseline-m3-v1` continues to be written.
- One command fits the model and writes the comparison report.

**Considerations:**
- The feature builder uses the same clock as `query_player_game_logs`: `event_time` before 16:00 UTC and `available_at` at or before it. A future `available_at` must not move the vector. A late fetch with an earlier `available_at` is visible. That test is the milestone's leak gate.
- A gap over 14 days sets `low_confidence` and leaves that row out of the headline MAE. The 3 June sample had gaps of 416 to 476 days. Those rows can appear in an appendix. They cannot be the win.
- `TimeSeriesSplit` on a frame that is not ordered by game date leaks. The split is a cut on dates.
- Random search waits until a fixed model beats the baseline on the holdout. Searching first spends the holdout.
- Lineup composition waits for M7. There is no starter table.
- Opponent defensive rating and pace are not columns. The points-allowed mean and the usage proxy are the substitutes, and the report calls them proxies.
- The daily job still learns tonight's game from a box score that does not exist yet. Replay and the training command are the milestone. The scheduler wire-up follows a schedule source that exists before tip.

**Branch points:**
- *XGBoost vs LightGBM vs CatBoost?* XGBoost, as `docs/CLAUDE.md` already locks. Chosen with the original roadmap.
- *Feature count?* Ten, listed above. Chosen 2026-11-07. More features wait until these ten beat the baseline on a legal holdout.
- *Quantile regression?* Skipped. M6 owns the distribution. Chosen with the original roadmap. The residual band exists so calibration has a number, and the report says what it is.
- *Replace the baseline?* No. Chosen 2026-11-07. The acceptance line is a comparison, so the baseline has to keep producing rows.
- *Train by dropping `ingested_at`?* No. Chosen 2026-11-07. Training uses `available_at`. Quotes stay on `quoted_at` and `ingested_at`. The note is `docs/provenance/available-at.md`.

**Acceptance:**
- On a declared holdout, with both clocks applied, XGBoost MAE is lower than the baseline on the same player-props, and the holdout is more than one game with history newer than 14 days. If no such holdout exists, the report says the comparison was refused and the milestone stays open.
- The residual band's Brier is reported next to the baseline's Brier on the same contracts. A lower MAE with a worse Brier is reported as mixed, not as a pass.
- Top 5 SHAP values are stored on each `xgb-m5-v1` row.
- One command reproduces the fit.
- `model_version` is stored on every prediction, and the baseline rows are still there.

---

## M6: Bayesian Wrapper

**Status:** Diagnostic only (2026-11-09). `uv run python -m app.models.posterior_fit` sampled points for 40 seeded players, 2 chains. R-hat and ESS did not clear the gate (`tau` R-hat 1.09 on ArviZ's 2-decimal rounding, bulk ESS 28). Subset Brier 0.163713 against the residual band 0.163925 on 581 contracts. That is not the acceptance sample. No `pymc-m6-v1` rows were written. After the same day's review, the gate treats a non-finite R-hat or ESS as a failure and the plot keeps mass below zero. That sample was not rerun. The note is `docs/provenance/m6-diagnostic.md`. The comparison target remains the M5 residual band, Brier 0.159651 on 18,878 headline contracts.

**Effort:** ~25-40 hours after the points model converges. A sampler that misses the diagnostic bar is a refusal, not a wider model.

**Goal:** Replace the single residual width with a posterior for one prop at a time. The XGBoost mean stays the location. A player intercept, pooled toward zero, is the only hierarchy. The milestone is a better Brier than `xgb-m5-v1` on the same holdout contracts, with the diagnostics beside it.

**Tasks:**
- Save or refit `xgb-m5-v1` inside the M6 command. A holdout covariate is the booster trained only on dates before 2025-12-05. The same clocks as M5: `event_time` before 16:00 UTC and `available_at` at or before it.
- Likelihood, points first: the stat is normal around `beta * xgb_mean + alpha_player`, with a shared `sigma`. `alpha_player` is normal around 0 with scale `tau`. `beta` is normal around 1. A player with no training games keeps `alpha` at 0.
- Ronnie writes the PyMC model. The harness around it builds the frame, samples, checks diagnostics, scores Brier, and writes the report.
- First NUTS run is a seeded 40-player subset, points only. It is a diagnostic. It is not the acceptance sample.
- Reported fit is every player with a legal training row, still points only, still the M5 date cut, headline rest at most 14 days. ADVI may be used while iterating. The reported number is NUTS.
- Rebounds and assists use the same formula only after the points diagnostics pass.
- Store `pymc-m6-v1` summaries on the holdout: posterior predictive mean, sd, and 10/50/90. `payload.distribution` is `posterior`. The trace is one NetCDF per prop under `models/`, which is gitignored. `baseline-m3-v1` and `xgb-m5-v1` stay.
- One command writes `docs/results/m6-posterior.md` and an SVG posterior predictive check.
- An ADR in `docs/adr.md` records the likelihood and the priors that were actually sampled.

**Considerations:**
- There is no position column. The pool is the player population. Role clusters wait for a column that exists.
- The daily job still has no game row before tip. The holdout command is the proof. The scheduler stays off.
- McElreath chapters 1-4 are the reading gate in the original list. The model text stays Ronnie's.
- A Brier win on the 40-player subset does not close the milestone.
- MAE is printed next to Brier. A better Brier with a worse MAE is a pass on this milestone. A worse Brier is not, even if the point prediction improved.
- NUTS on the full points population may take hours. That is acceptable for the reported run. It is not a reason to add parameters.

**Branch points:**
- *Position or role hierarchy?* No. Chosen 2026-11-09. Nothing in the tables defines a cluster.
- *Fit the hierarchy without the booster?* No. M5 already won the point comparison. M6 starts from that mean.
- *Quantile regression or a second residual width?* No. That would be another placeholder. The stored probability is the mean of the posterior predictive tail at the line.
- *ADVI as the published number?* No. ADVI is for iteration. The report's Brier is NUTS, or the milestone stays open.
- *Wire the nightly sampler?* No. Same reason as M5. A schedule source that exists before tip comes first.

**Acceptance:**
- On the M5 holdout, headline rest at most 14 days, the points posterior Brier is lower than the `xgb-m5-v1` residual Brier on the same contracts. The report states the contract count. Fewer contracts than the M5 score, or a fit that is only the 40-player subset, keeps the milestone open.
- R-hat under 1.01 and ESS above 400 for `beta`, `sigma`, and `tau`, read from the unrounded summary. A non-finite value fails. The sampler reports zero divergences. A posterior predictive plot is in the report, including the mass below zero.
- `pymc-m6-v1` rows exist for the scored holdout, and the M5 rows are still there.
- One command reproduces the fit.
- `docs/adr.md` records the model that was sampled.

---

## M7: Injury LLM Pipeline + Lineup-Conditional Layer

**Effort:** ~25-35 hours

**Goal:** Injury news flows from RSS feeds and official reports through an LLM classifier into structured prior updates. A lineup-conditional model predicts how usage and minutes redistribute when starters are out.

**Tasks:**
- Official NBA injury report ingestion (`nbainjuries` package)
- ESPN and Bleacher Report RSS feed scrapers
- LLM classification pipeline using Claude Haiku 4.5
- Prompt design: structured JSON output with `player`, `claim_type`, `severity`, `expected_games_missed`, `source`, `source_reliability_prior`, `confidence`
- Source reliability priors hard-coded for known beat reporters (refine later)
- `injury_signals` table storing classified outputs with timestamps
- Lineup-conditional usage redistribution model: small Bayesian model fit on historical games where starters were out
- Integration: when injury news lands, the lineup model updates affected players' projections through their priors

**Considerations:**
- Prompt design will take 2-3 rounds. Start with a basic prompt, classify 50 real news items, look at errors, refine. Repeat.
- The lineup-conditional model is genuinely interesting research. The simplest version: for each (player, prop) pair, fit a Bayesian regression of player's stat on "is starter X out" for each starter. Pool across players.
- LLM calls should be batched where possible. Anthropic's batch API gives 50% cost savings.

**Branch points:**
- *Haiku vs Sonnet for severity classification?* Default: Haiku. Test 100 items. If accuracy < 85%, switch to Sonnet for harder cases (keep Haiku as the default, fall back to Sonnet on uncertainty).
- *Drop ESPN/Bleacher Report if official reports are enough?* Default: keep both. They cover different time windows (official is 5pm day-before; news is real-time during the day).
- *Real-time Twitter monitoring?* PRD says no. Stick with that.

**Acceptance:**
- An injury news item is classified and stored with structured fields within 5 minutes of being scraped
- A simulated "Embiid out" event causes Maxey's projection to update meaningfully (test with synthetic data, verify the direction and magnitude)
- LLM classification accuracy on a held-out test set is documented

---

## M8: Dashboard MVP

**Effort:** ~25-35 hours

**Goal:** Three views are live: today's edges, player detail, and calibration. Mobile-friendly. Loads quickly.

**Tasks:**
- API endpoints: `/api/edges/today`, `/api/players/{id}/detail`, `/api/calibration/summary`
- Today's edges view: sortable table with player, prop, model probability, market price, edge, confidence indicator
- Player detail view: posterior chart (density or histogram), top SHAP features, recent injury signals
- Calibration view: calibration curve, Brier trend over time, edge realization plot
- Loading states, empty states, error states
- Responsive: works on phone

**Considerations:**
- TanStack Query for all data fetching. Stale time of 5 minutes for most views (matches the snapshot cadence).
- Posterior density charts are the visual differentiator. Use Recharts area chart or kernel density. The chart that shows "model thinks the distribution looks like this, market line is here" is the project's signature visual. Spend extra time on it.
- Don't over-design. A clean, functional dashboard beats a beautiful one that's late.

**Branch points:**
- *Add a "system status" page?* Default: yes, small effort. Shows ingestion freshness, job run history. Useful for debugging.
- *Add a backtest replay view?* Default: no for v1. The `docs/results/` reports are enough.

**Acceptance:**
- Dashboard loads at production URL
- Mobile view works
- Three core views functional
- Page load (FCP) under 2 seconds on a typical connection

---

## M9: Alerts

**Effort:** ~10-15 hours

**Goal:** Discord webhook notifications fire when high-confidence edges appear. Deduplicated. Volume-capped.

**Tasks:**
- Edge detection job (every 5 min during game windows)
- Threshold config via env vars: minimum edge, minimum confidence, minimum liquidity
- Deduplication: same (player, prop, game) doesn't alert twice within 2 hours unless the edge moves significantly
- Discord webhook delivery with rich payload (player name, line, model probability with CI, market price, edge, dashboard link)
- Alert logging to `alerts_sent` table for later analysis (did the alerted edges actually realize?)
- Volume cap: hard limit on alerts per hour

**Considerations:**
- Start with conservative thresholds. Wait for the dashboard to be running and tune based on observed alert volume in your first week of live data.
- Failure mode: if Discord webhook is down, alerts log to a "failed" table but don't crash the scheduler.
- Alert quality > alert quantity. Five high-conviction edges per week is much better than fifty noisy ones.

**Branch points:**
- *Discord vs email vs push?* Discord is easiest, sufficient, and doesn't require user setup.
- *Notifications panel inside the dashboard?* Default: no for v1.

**Acceptance:**
- A simulated edge triggers a real Discord notification with all required fields
- Dedup prevents same-edge alerts within the window
- Volume cap works

---

## M10: Polish & Deploy

**Effort:** ~10-20 hours

**Goal:** The project is portfolio-ready. README is recruiter-friendly. Docs are complete. CI is green. Demo link is live.

**Tasks:**
- README rewrite: full version with screenshots, GIF of the dashboard, demo link, architecture summary, "how to run locally" section, link to the model card and results docs
- `docs/model_card.md`: what the model does, what it doesn't, current calibration, intended use, limitations
- `docs/architecture.md`: system diagram, data flow, key design decisions
- `docs/results/`: at least one polished backtest report on a full season
- All CI green, branch protection on main
- Final security audit: grep for secrets, scan with `trufflehog`, rotate anything suspicious

**Considerations:**
- The README is the front door. Spend real time on it. Recruiters spend 30-60 seconds on a repo's README. Make those seconds count.
- A 60-second Loom video walking through the dashboard is high-leverage. Embed it in the README.
- Pin the most impressive backtest result in the README's top section.

**Branch points:**
- *Add a blog post explaining the methodology?* Default: optional but strongly recommended. Even a single dev.to or personal-site post explaining the Bayesian approach is interview gold.
- *Submit anywhere?* Show Hacker News, the SABR (sports analytics) community, the rsports-betting subreddit. Optional.

**Acceptance:**
- README has screenshots, GIF, demo link, architecture summary, model card link, results link
- All CI green
- No secrets in repo (audit passes)
- Repo can be cloned and run by a stranger following the README

---

## After v1

If you ship v1 well, the v2 roadmap items in `docs/CLAUDE.md` become the natural next set of features: pgvector for player similarity, additional prop types, game-script awareness, an LLM agent layer over the dashboard. Pick one or two; don't try all.

Equally valid: stop at v1. A clean, complete v1 is more impressive than a sprawling, half-finished v2.

## Working principles for this roadmap

A few rules to keep this document useful as it ages:

- **When a milestone drifts:** if a milestone runs 50% over its estimated effort, stop and reassess. Is the scope right? Is something off in the architecture? Do you need to descope? Don't push through silently; update the doc.
- **When a branch point is hit:** when you actually hit one of the branch points listed in a milestone, add a one-line note to the milestone explaining what you chose and why. This becomes your decision history.
- **When you skip a milestone:** if you skip a milestone or merge two together, edit this doc to reflect that. Don't leave stale milestones cluttering the plan.
- **When something not on the roadmap appears:** add it. The roadmap is allowed to grow. It is not allowed to stay stale.

The roadmap is a tool, not a contract. Use it.
