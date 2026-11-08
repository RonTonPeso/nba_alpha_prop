# M5 plan: what changed before any model code

Written 7 Nov 2026, before implementation. The fit that followed this spec is `docs/provenance/m5-xgb.md`. The audience is someone asking why the milestone no longer matches the original task list.

## Where this aims

`docs/Roadmap.md` M5 acceptance, as revised the same day:

- On a declared holdout, with both clocks applied, XGBoost MAE is lower than the baseline on the same player-props, and the holdout is more than one game with history newer than 14 days. If no such holdout exists, the report says the comparison was refused and the milestone stays open.
- The residual band's Brier is reported next to the baseline's Brier on the same contracts. A lower MAE with a worse Brier is reported as mixed, not as a pass.
- Top 5 SHAP values are stored on each `xgb-m5-v1` row.
- One command reproduces the fit.
- `model_version` is stored on every prediction, and the baseline rows are still there.

`docs/PRD.md` section 6.2 asks for a reproducible XGBoost fit on at least two seasons, with rolling averages, opponent defense, pace, rest, home, usage, and lineup, compared with the baseline. Two seasons and lineup are not available under the clocks and the tables we have. The roadmap revision says so. The PRD line is not silently checked off.

## What the original list assumed

The original M5 list replaces the baseline, trains with `TimeSeriesSplit`, searches 30 to 50 hyperparameter draws, and ships lineup, pace, defensive rating, and usage. The comparison that would decide success is an out-of-sample MAE and a better calibration.

The 7 Nov review of M4, recorded in `docs/provenance/m4-calibration.md`, showed what that comparison would actually be given the current database. All 105 scored contracts are one game, 3 June 2026. The 2025-26 regular season was ingested on 5 June at 21:13 UTC, so that game's visible history ends in 2024-25. Stored rest gaps on the contract rows run from 416 to 476 days. Loaded markets begin on 25 March 2026. A model that "beats the baseline" on that night has learned a stale window, or one game, or both.

## Decisions

### The baseline stays.

The original task says the XGBoost model replaces the baseline in the daily job. The acceptance line is a comparison. A comparison needs both `model_version` values on the same player-props. `baseline-m3-v1` keeps being written. `xgb-m5-v1` is added beside it.

Rejected: turning the baseline off once the new model exists. The next review would have no paired MAE.

### Ten features, from columns that exist.

`player_game_logs` has minutes and the counting stats, including field-goal attempts, free-throw attempts, and turnovers. `game_results` has the two scores. There is no pace column, no defensive-rating column, and no starter flag. Play-by-play was deferred to M7.

The ten features are the two points windows, the 15-game rebounds and assists means, minutes, home, capped rest, a usage proxy, opponent points allowed, and capped days since a 30-point game. One booster per prop, because a points residual would dominate a single model that also predicts assists.

Rejected: lineup composition in this milestone. Anything called a lineup here would be invented.

Rejected: naming the proxies "defensive rating" and "usage rate." The report has to say they are box-score stand-ins.

### The split is a cut on game date.

sklearn's `TimeSeriesSplit` leaks if the frame is shuffled, and it leaks if two players from the same game fall on opposite sides of a row cut. The holdout is the last slice of `game_date`. Feature code may only read `query_player_game_logs` at 16:00 UTC on that date. A future `available_at` must leave the vector unchanged. A late `ingested_at` with an earlier `available_at` is visible. That is the clock `test_point_in_time.py` locks.

Rejected: k-fold. The original roadmap already rejected it. Repeating it here because a random split of 2022-26 would let April train on May.

### The first fit uses fixed hyperparameters.

Random search of 30 to 50 draws, on a holdout that may be a handful of dates, will fit the search to the holdout. The first command uses one configuration. Search starts only after that configuration beats the baseline on MAE, and the search stays inside the training dates.

### A gap over 14 days is not a win.

The baseline set `low_confidence` from the count of games and then applied a rest effect at a 400-day gap. M5 caps the rest feature at 14 days, sets `low_confidence` when the raw gap is longer, and keeps those rows out of the headline MAE. They can be listed in the report. The 3 June contracts are in that bucket.

Rejected: dropping the long-gap rows from the database. They are a true output of the clock. The exclusion is from the acceptance comparison only.

### The probability is a training residual, and it is labeled as one.

M5 acceptance includes calibration. A point prediction has no Brier score. The stored standard deviation is the residual spread of the training predictions, constant for that fit, passed through the same normal tail M4 already scores. The payload says `distribution: residual-normal`. M6 replaces it.

Rejected: quantile regression in this milestone. The original branch point skipped it because M6 owns the distribution. A second uncertainty system, built to pass a calibration line, would be the thing M6 is supposed to replace.

### The bulk clock was chosen after this plan.

The options from the 7 Nov review were strict forward-only, a new `available_at`, or a flag that ignores `ingested_at`. The flag stays rejected. Rewriting `ingested_at` stays rejected.

The choice, made the same day and written up in `docs/provenance/available-at.md`, is `available_at`. Bulk box scores and game results are known at 12:00 UTC the day after `game_date`. A live fetch sets `available_at` equal to `ingested_at`. Training and the baseline comparison both use that column. Reports say the history clock was reconstructed. No booster starts in that change.

## What would make this plan wrong

- A holdout of several weeks where both clocks pass and the history gap is under 14 days, on which the ten features lose to the 15-game mean by a wide margin. The feature list is then too close to the baseline to be the milestone, and the next features have to come from columns we refused here, or from M7.
- The residual band's Brier beating the baseline while the MAE loses. The plan treats that as a mixed result. If the product decision is that calibration is the only acceptance line, the MAE gate is the wrong one.
- Opponent points allowed moving the prediction when the opponent's games have `available_at` after the clock. A test for the feature vector is the check. A green MAE with that test failing voids the milestone.

## What was not done

No booster was fit. No dependency was added. The clock migration is a later change, recorded in `docs/provenance/available-at.md`, and it is not an M5 result. The 3 June numbers cited above this section are the old `ingested_at` replay: 105 contracts, one game, rest gaps 416 to 476, markets beginning 25 March 2026.
