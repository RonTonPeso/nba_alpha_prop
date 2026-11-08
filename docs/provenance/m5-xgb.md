# M5 XGBoost fit

## What this is for

`docs/Roadmap.md` M5 acceptance, as revised before this fit:

- On a declared holdout, with both clocks applied, XGBoost MAE is lower than the baseline on the same player-props, and the holdout is more than one game with history newer than 14 days. If no such holdout exists, the report says the comparison was refused and the milestone stays open.
- The residual band's Brier is reported next to the baseline's Brier on the same contracts. A lower MAE with a worse Brier is reported as mixed, not as a pass.
- Top 5 SHAP values are stored on each `xgb-m5-v1` row.
- One command reproduces the fit.
- `model_version` is stored on every prediction, and the baseline rows are still there.

The spec those lines come from is `docs/provenance/m5-plan.md`. The feature clock is `available_at`, recorded in `docs/provenance/available-at.md`.

## The choice

One booster per prop, trained with XGBoost's own `train` API. Fixed settings: 200 rounds, depth 4, learning rate 0.05, subsample 0.8, column sample 0.8, min child weight 5, lambda 1, histogram trees, seed 0, one thread. The holdout is the last 20 percent of distinct `game_date` values, so every player in a game stays on the same side of the cut. The holdout is not an eval set. No search was run.

The ten features are the ones named in the roadmap. Home or away is the previous visible game's team. Rest enters the model capped at 14 days. A raw gap over 14 sets `low_confidence` and leaves that row out of the headline MAE. The row stays in training. `usage_share` is the player's FGA + 0.44*FTA + TOV divided by that sum for the whole team in the same games, including the player. Opponent signal is points allowed over the last 15 visible games. The stored spread is the sample standard deviation of training residuals around the clipped mean, floored at 0.5, labeled `residual-normal`. SHAP is XGBoost `pred_contribs`, top 5 by absolute value.

The comparison baseline is `forecast_prop` on that same visible history, not a previously stored row.

Rejected: the scikit-learn wrapper. It imports scikit-learn, and the training API already fits a booster and returns the contributions.

Rejected: a usage ratio whose denominator is teammates only. That number is not bounded and is not a share of the team's box score.

Rejected: random search on this holdout. The plan says search waits until a fixed fit beats the baseline, and it stays inside the training dates. This fit did beat the baseline. Search is still a later step, not this command.

Rejected: wiring the daily job. The job still learns tonight's game from a box score that does not exist yet.

## What the command did

From `backend/`, `uv run python -m app.models.fit` on 7 Nov 2026. Copied from that run, and matched by a second run that inserted nothing:

- Loaded 112,884 player-games.
- Holdout starts 2025-12-05. Training dates 667, holdout dates 167. Training player-games 86,759. Holdout player-games 21,184.
- Headline games 993. XGBoost MAE 2.627, baseline MAE 2.776, on 62,271 player-props.
- Points 4.603 vs 4.889, rebounds 1.920 vs 2.021, assists 1.358 vs 1.419, each on 20,757 player-props.
- Residual standard deviations: points 6.002, rebounds 2.509, assists 1.803.
- Brier 0.159651 vs 0.168920 on 18,878 headline contracts.
- Verdict: pass.
- Kalshi-resolved players, same rest cap: MAE 3.024 vs 3.200 on 23,514 player-props, 992 games.
- Rest over 14 days, not the acceptance sample: MAE 2.098 vs 2.294 on 1,281 player-props, 311 games.

The report is `docs/results/m5-xgb.md`.

The first run inserted 63,552 `xgb-m5-v1` rows and 63,372 new `baseline-m3-v1` rows. A stored points row checked after that insert has `distribution` `residual-normal`, five SHAP entries, and `usage_share` as the first of those five. Table counts after the insert: 68,703 baseline rows and 63,552 `xgb-m5-v1` rows. The second run inserted 0 of each and printed the same MAE and Brier.

`uv run mypy app tests` reported no issues in 55 source files. After the fit, `uv run pytest -q` reported 105 passed.

## What would make the pass the wrong claim

The headline MAE averages points, rebounds, and assists in one number. A large points gain could hide an assists loss. On this fit each prop moved the same way, so that mix is not what produced the pass. A later fit where one prop loses has to say so even if the pooled MAE still falls.

The Brier uses one residual width per prop, fit on the training rows. A lower Brier can be a wider or narrower band rather than a sharper mean. The MAE is the check on the mean. M6 is still the distribution.

The 180 Finals `baseline-m3-v1` rows that already existed were not rewritten. Some of those were stored under `ingested_at`. The report's baseline is the recomputed `forecast_prop`. It is not those 180 stored means.

A later change to the formula that keeps `xgb-m5-v1` will skip the stored rows and the table will disagree with a new report. This second run still matched, because nothing in the fit had changed.

## What was not verified

Quotes were not scored. The scheduler was not started. Hyperparameter search was not run. `libomp` had to be installed on this Mac before XGBoost would import (`brew install libomp`). A machine without that library cannot run the command.
