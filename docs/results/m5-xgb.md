# M5 XGBoost comparison

Model version: `xgb-m5-v1`.
Baseline version: `baseline-m3-v1`, recomputed on the same visible history.
Stored baseline rows from an earlier clock are not these numbers.

This is one booster per prop. It is not a posterior.
The stored spread is the training residual of the clipped mean.

Features use the 16:00 UTC clock.
`event_time` has to be before that clock.
`available_at` has to be at or before that clock.
For a bulk-loaded box score, `available_at` is 12:00 UTC on the
day after the game. `ingested_at` is the fetch time and is not
the feature clock. Quotes are not scored in this comparison.

Holdout starts: 2025-12-05 (last 20% of game dates).
Training dates: 667. Holdout dates: 167.
Training player-games: 86759. Holdout player-games: 21184.

Headline keeps raw rest of 14 days or less.
A longer gap is low_confidence and is listed after the headline.
Headline games: 993.
XGBoost MAE: 2.627 on 62271 player-props.
Baseline MAE: 2.776 on 62271 player-props.
points MAE: XGBoost 4.603 on 20757 player-props, baseline 4.889 on 20757 player-props.
rebounds MAE: XGBoost 1.920 on 20757 player-props, baseline 2.021 on 20757 player-props.
assists MAE: XGBoost 1.358 on 20757 player-props, baseline 1.419 on 20757 player-props.
Verdict: pass.

Brier uses P(stat >= line) from each model's normal band,
on headline player-props that have a Kalshi line.
XGBoost Brier: 0.159651 on 18878 contracts.
Baseline Brier: 0.168920 on 18878 contracts.

Players a Kalshi market has been resolved to, same headline rest cap:
Games: 992.
XGBoost MAE: 3.024 on 23514 player-props.
Baseline MAE: 3.200 on 23514 player-props.

Rest over the cap, not the acceptance sample:
Games: 311.
XGBoost MAE: 2.098 on 1281 player-props.
Baseline MAE: 2.294 on 1281 player-props.

Features, in column order: `pts_mean_5`, `pts_mean_15`, `reb_mean_15`, `ast_mean_15`, `min_mean_15`, `is_home`, `rest_capped`, `usage_share`, `opp_pts_allowed_15`, `days_since_30_capped`.
`usage_share` divides the player's FGA + 0.44*FTA + TOV by that
sum for every teammate on the same team in those games, including
the player. `opp_pts_allowed_15` is the opponent's points allowed.
Neither name is a defensive rating or a play-by-play usage rate.

Fixed hyperparameters: `num_boost_round=200`, `max_depth=4`, `eta=0.05`, `subsample=0.8`, `colsample_bytree=0.8`, `min_child_weight=5`, `lambda=1.0`, `objective=reg:squarederror`, `tree_method=hist`, `seed=0`, `nthread=1`.
No search was run. The holdout was not an eval set.

MAE improved and the residual Brier was not worse on the headline contracts.
