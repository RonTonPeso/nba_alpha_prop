# Retrospective review: M5, M6, M7, M8

Fresh session review of the largest milestones that did not get a Layer-3
pass after merge. M10 polish was out of scope. M4 and the M6 diagnostic
were already reviewed.

**What was run:** read-only queries against the local dev DB, plus two
read-only scratch scripts (M6 width breakdown, Embiid→Maxey by season).
One unintended side effect: about 100 Haiku calls on the local key.
`engine.py` reloads `.env` on import, which put the key back after it was
unset.

---

## Summary

Three findings change what the repo can honestly claim right now:

1. **M6 stores the wrong distribution, and the dashboard uses it.** The
   `pymc-m6-v1` rows hold the posterior of the mean, not the posterior
   predictive. For points the stored std is 0.48 when it should be about
   6.7. The M6 Brier numbers are still correct because the report scores
   straight from the trace. But M8 computes probabilities from the stored
   rows: on its default slate, 98 of 108 model probabilities come out
   below 2% or above 98%.
2. **The M7 "1.000 on 100" LLM accuracy proves nothing.** The set is 15
   template sentences repeated to make 100 rows. The 30-line regex
   fallback also scores 1.000 on it, and an empty player prediction counts
   as correct.
3. **The M7 live trigger doesn't do what ADR-5 says.** An "out" claim
   never expires and is never cleared by a later "available". Opponents
   get treated as teammates. The committed effects file includes effects
   fit from PHI's opponents' sparse games, and departed starters are
   counted as "out".

Also important:

- 61–86% of M6's Brier gain over M5 comes from a wider single width, not
  from the hierarchy.
- The holdout was used to choose between M6 variants.
- CI skips every Postgres test, including the point-in-time leak tests.
- M5 is the cleanest milestone and has nothing blocking.

**Suggested fix order:**

1. M6 B1, since it's live on the dashboard.
2. M7 B1, since the claim is public.
3. Postgres in CI.
4. The M7 trigger bugs, before the scheduler is ever turned on.

---

## M7

### Blocking

**B1. The held-out LLM accuracy is not a measurement.** Files:
`docs/results/m7-llm-heldout.jsonl`, `m7-llm.md`,
`backend/app/data/injury/eval_heldout.py:55,96`

- The 100 rows are 15 unique texts about 11 players, with 85
  `example.com` URLs. Every sentence contains its own label word, e.g.
  "Joel Embiid out with knee."
- `_rule_based_classify` offline on the same file: claim, player and joint
  accuracy all 1.000. A regex ties Haiku, so the set can't tell them
  apart.
- `player_ok` checks `gold in pred or pred in gold`. Since `"" in gold` is
  always true, an empty prediction scores as correct (9 rows in the regex
  run).
- With no API key, `classify_item` silently falls back to the regex. The
  report still prints "Default model: Haiku 4.5" without reading the model
  each row actually used.
- The claim is public: Roadmap M7 status line, and ADR-5 leans on it. The
  plan called for classifying real items and looking at the errors.

### Important

**I1. An "out" claim never goes stale.** `lineup_apply.py:40-55`,
`queries.py:56-61`

- Signals are read newest first, but non-out claims are skipped before
  the player is marked as seen. So a later "available" or "return" never
  overrides an earlier "out". The only expiry is `limit=500`.
- Claims aren't tied to a game or date, so a three-week-old "out tonight"
  still fires.
- Dev DB already holds `synthetic://embiid-out-m7` at confidence 0.99
  (signal id 11). Any `--game-id` run on a PHI game in that DB will treat
  Embiid as out.

**I2. Opponents count as teammates, and there's no usual-starter check at
inference.** `lineup_apply.py:135`

- `team_players` covers every player with a base prediction in the game,
  which means both teams. Effects are keyed only by player IDs.
- Example: a "Tobias Harris out" claim would push a +1.79 points shift
  onto Maxey on the other team.
- ADR-5 says the trigger applies to a usual starter, but nothing checks
  that at inference.
- The base forecast is a 15-game rolling mean, so it already reflects a
  long absence. Adding the delta on top double counts.
- The fit only counts the first ~5 games of an absence as "out". Training
  and inference disagree on what "out" means.

**I3. The labels include departures, and opponents' timelines are
sparse.** `lineup.py:118-145`

- "Out" means a usual starter who didn't start. A traded or departed
  starter is counted "out" for about 5 games.
- Harris has 5 "out" games in 2024-25 after he left PHI, inside the
  n_out=20 behind his Maxey effect.
- Backfilling with `--team PHI` also flags the opponents' players. BOS,
  NYK, ORL and the rest end up with timelines made only of their games
  against PHI, spread across seasons.
- 180 of the 1,296 committed effects have a non-PHI injured player.
  Example: Banchero out gives Franz Wagner +3.5 points, from n_out=3
  (raw +13.0).
- "Didn't start" also covers a starter who came off the bench, while the
  live trigger means "won't play".
- The provenance note says other teams can be added later without code
  changes. But the current artifact already contains these opponent
  effects, and it loads by default.

**I4. The Embiid→Maxey acceptance check doesn't test magnitude.**
`lineup_apply.py:165,205-210`, `tests/test_lineup.py:30-49`,
`adr.md:437`

- The lift is exactly `delta`, so `lift >= max(0.5, 0.5*delta)` reduces to
  `delta >= 0.5`. The provenance line "3.272 ≥ floor 1.636" checks the
  effect against itself.
- By season, Maxey with Embiid "out" vs started (same labeling rule):

  | Season  | Lift | n out |
  | ------- | ---- | ----- |
  | 2022-23 | +7.2 | 11    |
  | 2023-24 | −0.1 | 10    |
  | 2024-25 | +2.6 | 13    |

- The within-season average (about +3.3) is close to the pooled +4.0 raw,
  so there's no big era bias. But there's no interval, and "meaningfully"
  isn't tested against anything.
- There's no pytest for this. The only test uses a hand-typed `delta=4.5`,
  which is exactly what ADR-5 says the test does not do.

**I5. Injury news bypasses the hybrid stack.**
`lineup_apply.py:89-102,120`, `api/versions.py:6-11`

- The base model defaults to `baseline-m3-v1`. The std is copied unchanged,
  so a delta estimated from 10–35 games adds no uncertainty, and the
  output is a plain normal.
- M8 prefers `lineup-m7-v1` over `pymc-m6-v1`. So whenever injury news
  fires, the dashboard drops from the posterior to the baseline plus a
  delta.
- Roadmap lines 353-354 promise a "small Bayesian model" that "updates
  projections through their priors". Commitment 3 isn't met. Commitment 2
  is met in spirit, since the delta is fit and not hand-set, except for
  `self_out`, which zeros the mean.

**I6. The stored acceptance row can't be reproduced and isn't
point-in-time.**

- The one `lineup-m7-v1` row carries `payload.synthetic: true`, a key no
  committed code writes. No committed command inserts the synthetic
  signal either.
- Its `prediction_time` is 2026-11-27, for a game played 2026-05-10. The
  effects were fit as of now, so they include that game's own result.
- The row sits in `predictions`, and M8 displays it.

**I7. A silent regex fallback can fire the trigger.**
`classify.py:141-145,165-169,83-85`

- With no key, or on any API error (429, timeout), the regex takes over.
  It labels any text containing "out" as `out` at confidence 0.7, and the
  trigger threshold is 0.5.
- Example: "Tyrese Maxey drops 40 as Sixers knock Knicks out" would mark
  Maxey as out.
- `active_out_player_ids` never checks `classifier_model`.

**I8. Items are classified before the duplicate check.**
`pipeline.py:175-182`, `scheduler.py`

- Each RSS tick classifies up to 40 items, then finds most of them already
  stored.
- The official job re-pulls the same 17:30 report every hour and
  classifies up to 80 rows.
- That's up to ~5.7k Haiku calls a day, plus Sonnet fallbacks, almost all
  on items already stored. Price that against the $25/month budget before
  enabling the scheduler.

**I9. Official report times are off by 4–5 hours.**
`sources.py:125-128,154-156`

- Eastern wall time is tagged as UTC, and the default report time uses the
  machine's local clock.
- This doesn't leak into replay, because `available_at` is the scrape
  time. But `event_time` is the sort key, so the order between official
  and RSS claims is wrong. That matters once I1 gets a "latest claim wins"
  rule.

### Test gaps

- These have no tests at all: `fit_lineup_effects`, `active_out_player_ids`,
  `apply_*`, `backfill_game`, the clock filters in `query_injury_signals`,
  the Haiku client path (with a fake client), the Sonnet fallback, and the
  eval scorer.
- `test_rule_based_classify_out` asserts `"Embiid" in name or name == ""`,
  which passes when the name is empty.

### Suggestions

- **Use real structured output.** The prompt asks for JSON in plain text.
  The timed run lost 1 of 10 items to a parse error ("Extra data"), and
  `m7-injury.md` doesn't mention it. Also, `confidence or 0.5` turns 0 into
  0.5.
- **Trigger and source handling:** `source_reliability_prior` is stored but
  never used by the trigger. The official report's status is already
  structured, so map it directly and save the LLM for RSS.
- **LLM logging:** CLAUDE.md asks you to log request ID, latency and token
  count. None of them are logged.
- **Small code issues:**
  - `low_confidence=... or True` is always true.
  - The usual-starter logic is duplicated, and
    `starter_backfill.py:142-233` is unused.
  - Use `defusedxml` for the RSS feeds.
  - The fallback model is Sonnet 4.5, while CLAUDE.md says 4.6.
- **Say the backfill rule in ADR-5:** the starter backfill edits fact rows
  in place. That's defensible, since starting is a post-game fact, but
  ADR-5 should state it.

### What's done well

- Training labels come from box-score starters and the live trigger comes
  from signals. Using minutes as the label was rejected as circular, in
  writing, before any code.
- `injury_signals` carries both clocks and the query uses both.
  `available_at` is the scrape time, so the timestamp bugs can't leak into
  replay.
- Adjusted forecasts get a new model version instead of overwriting old
  rows. The plan wrote down its failure conditions in advance, including
  "do not invent a constant".

---

## M5

### Blocking

None.

### Important

**I1. The residual band is computed in-sample and is too narrow.**
`boost.py:68-79`, `fit.py:561-563`

- The out-of-fold widths M6 later learned are wider: points 6.65 vs 6.00,
  rebounds 2.77 vs 2.51, assists 2.25 vs 1.80.
- Swapping in only the wider width on the same holdout contracts improves
  the Brier:

  | Prop     | M5 width | Wider width |
  | -------- | -------- | ----------- |
  | Points   | 0.158157 | 0.157820    |
  | Rebounds | 0.168264 | 0.167646    |
  | Assists  | 0.150863 | 0.148268    |

- So all 63,552 stored `xgb-m5-v1` rows are overconfident. The report
  correctly says "training residual", but not that this is optimistic.

**I2. The training loader reads the latest version, not the version as of
the prediction.** `fit.py:348-358,386-393`

- `DISTINCT ON ... ORDER BY ingested_at DESC` is the current-state read
  that commitment 1 warns against.
- It's dormant today, because there's only one version per key. It becomes
  a leak the day a stat correction lands. At minimum, assert one version
  per key.

### Test gaps

- **Leak gate at the vector level:** it's tested at `visible_logs`, not on
  the full vector. Nothing checks that adding a future-available row for
  the same player leaves `build_feature_row` unchanged. The opponent
  version of that test does exist.
- **Example building:** `build_examples` and `_team_usage`
  (`fit.py:419-423`, which reads rows without a clock) are untested.
- **Acceptance lines:** nothing checks that stored rows carry `shap_top5`
  or that baseline rows are left untouched.

### Suggestions

- Reuse `_out_of_fold_means` from M6 to compute the M5 width, and ship it
  as a new model version.
- PRD 6.2's low-confidence flag also asks for small sample, unusual lineup
  and out-of-distribution opponent. M5 only flags the rest gap.

### What's done well

- **Honest holdout:** the date cut keeps each night on one side,
  hyperparameters are fixed with no search on the holdout, and long-gap
  rows are reported but kept out of the headline.
- **Clock design:** the `available_at` decision is well reasoned, with
  written rejections of rewriting `ingested_at` and of an "ignore" flag.
- **Honest reporting:** proxies are named as proxies, MAE is shown per
  prop, and a second run reproduced the numbers exactly.

---

## M6

### Blocking

**B1. Stored rows hold the posterior of the mean, not the posterior
predictive.** `posterior_fit.py:320-328,385-388`, ADR-4 `adr.md:378`

- `_latent_draws` returns `beta*center + alpha` for each draw. `sigma`
  never enters.
- In the DB, the average stored std is 0.48 for points and about 0.19 for
  rebounds and assists. The points 10–90 range is 1.24 points, against
  14.3 for M5.
- The report's Brier is unaffected because it uses `tail_probability`.
- The same bug means the "posterior predictive mean" MAE (`:349-352`) is
  really the mean of the location.

### Important

**I1. Most of the win over the M5 band is just a wider width.**

| Prop     | M5 band  | Booster + posterior sigma, no intercepts | Full posterior | Share of gain from width |
| -------- | -------- | ---------------------------------------- | -------------- | ------------------------ |
| Points   | 0.158157 | 0.157820                                 | 0.157604       | 61%                      |
| Rebounds | 0.168264 | 0.167646                                 | 0.167548       | 86%                      |
| Assists  | 0.150863 | 0.148268                                 | 0.147801       | 85%                      |

- The middle column is a fair pre-holdout comparison: that sigma was
  learned only from training-period out-of-fold residuals.
- The player intercepts add 0.0001–0.0005. ADR-4 and the essay credit the
  hierarchy for the win.

**I2. The holdout picked the model.** `posterior_fit.py:682-702`

- At least six variants were scored on holdout contracts. The orthogonal
  assists variant was rejected on a 40-player holdout Brier.
- Rows are only written if `posterior_brier < residual_brier` on the
  holdout.
- The margins are 0.0006, 0.0007 and 0.0031, with no uncertainty, and
  contracts are correlated within each player-game. A bootstrap by game
  would probably show points and rebounds as ties, but that was not run.
- The M5 plan's own rule applies: "Searching first spends the holdout."

**I3. The docs disagree about who wrote the model.**

- The docstrings in `posterior_model.py:1-8` and `posterior.py:1-6` still
  say "diagnostic" and "Ronnie replaces the priors before an acceptance
  fit".
- ADR-4 is honest that the agent typed the likelihood. But the Roadmap
  closes M6 without marking the task "Ronnie writes the PyMC model"
  (line 306) as unmet.

### Test gaps

- **Stored rows:** nothing tests `_store_posterior`. One test checking
  stored std ≈ √(sigma² + var(mu)) would have caught B1.
- **Out-of-fold:** `_out_of_fold_means` is untested. A test should check
  that no row is predicted by a booster that saw its own date block.
- **Holdout exclusion:** this one is tested, which is good.

### Suggestions

- **Record the variant:** the payload doesn't say whether beta was fixed
  or which trace was used, and one model version covers three
  parameterizations.
- **Trace loading:** `--from-trace` prints the command-line `tune` value,
  not the trace's (`:594-600`), and nothing checks that a loaded trace
  matches the flags.

### What's done well

- **Sampler inputs:** the out-of-fold covariate fixes the in-sample
  covariate problem from the diagnostic review.
- **Diagnostic gate:** it reads unrounded R-hat and ESS, fails on NaN, and
  requires zero divergences. A stuck `tau` is tested through arviz.
- **ADR-4:** it records variants that had a better Brier but were refused
  for identifiability. Good judgment, and well documented.

---

## M8 (light pass)

**Blocking (inherits M6 B1).** `comparisons.py:137`,
`routes.py:135-137,162`

- On the default slate (2026-06-03), 98 of 108 rows have a model
  probability below 2% or above 98%. Example: Karl-Anthony Towns points
  24.5 → 0.00, and 9.5 → 1.00.
- The density chart is a spike. Once mids exist, these rows will top the
  Today view.

**Important**

- **Post-tip mid fallback.** `comparisons.py:140-148`,
  `routes.py:165-167`: when there's no mid before tip, the code uses the
  latest snapshot as of now. For past slates that's a settled or in-game
  price, and nothing labels it. That breaks the point-in-time rule on the
  page meant to look honest.
- **The synthetic lineup row is shown.** The version preference surfaces
  it, and any lineup row downgrades the display to baseline (see M7 I5).
- **Paths break in Docker.** `routes.py:54-55` and `lineup.py:26-27`
  resolve paths with `parents[3]`. In the image (`Dockerfile:25-27`,
  WORKDIR /app) that resolves to `/`. So `/api/calibration/summary` would
  return "report missing", and the lineup artifact wouldn't load. This is
  from reading the Dockerfile, not from a build, and it stays latent while
  Railway is deferred.

**Suggestions**

- The calibration bins come from the baseline's 108-contract replay, not
  the model shown on Today. Make that visible in the UI.
- The test fixture's `std=6.0` can't catch B1.

**Done well:** "Not an edge or EV claim" in the copy, gap fields with no
edge key, and mids read on the quote clock at 16:00 UTC.

---

## Cross-cutting

1. **CI never runs the Postgres tests.** `ci.yml` has no Postgres service,
   and `conftest.py:31-40` skips silently when it can't connect. That
   includes `test_point_in_time.py`, which is PRD 6.2's leak regression
   test; it has only ever run locally.
2. **The `predictions` table mixes replay, live and synthetic rows with
   no marker.** M5 and M6 use a replayed `prediction_time`, M7 uses
   wall-clock time, and the synthetic row is flagged only inside its
   payload. A `run_kind` column plus a "before tip" filter in the API
   would fix this.
3. **Commitment 3 only exists offline.** XGB→PyMC runs as a holdout
   replay. The daily job is still the baseline, and injury news bypasses
   the posterior. Each piece is documented somewhere, but nowhere in one
   place.
4. **`load_dotenv` at import** (`engine.py:19`) means unsetting the key
   in your shell doesn't stop API calls, and a missing key in production
   silently switches to the regex. Make the classifier mode explicit and
   fail loudly in eval and in the scheduler.
5. **The README on main** may still lag if M10 was not yet merged when
   this review ran; check current `README.md`.
6. **Security:** no secrets are committed, and `.env.example` is blank.
   News text and parsed LLM output are persisted, as the PRD requires,
   without full prompts. Prompt-injection risk from these feeds is low,
   but the LLM output feeds the trigger with no guard (M7 I7).
