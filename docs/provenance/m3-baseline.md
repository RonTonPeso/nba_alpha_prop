# M3 baseline: why it is built this way

Written 6 Nov 2026, while implementing the milestone. The audience is someone asking why each choice was made, including the ones that look arbitrary.

## Where the work started

Local `main` was already at `c65c419`, the tip of `kalshi-pipe`. That is three commits ahead of `origin/main`. M0, M1, and M2 are done in that tree. `docs/Roadmap.md` names M3 next: a dumb baseline, a `predictions` table, a daily job, and a replay harness. `docs/process.md` says the same thing at the top of the M2 close note.

M4 (Brier, calibration plots, CI smoke backtest), M5 (XGBoost), and M6 (PyMC) were left alone. The roadmap's own branch point says not to skip the baseline. A stronger model on a leaking pipeline would hide the bug the baseline is supposed to expose.

The nested folder `nba_alpha_prop/nba_alpha_prop` is a second checkout of the documentation branch from the earlier cloud session. It does not contain the Kalshi code. This work is on branch `m3-baseline` in the outer repo.

## What "done" means here, and what does not

Roadmap acceptance for M3:

- Predictions are stored with a point-in-time timestamp. Implemented. `prediction_time` is 16:00 UTC on the game date. The regression tests in `backend/tests/test_baseline_db.py` show a future game and a late-ingested game do not move the mean.
- `python -m app.backtest.run --start 2025-01-01 --end 2025-01-31` writes a report. The command exists. Against the local database on 6 Nov 2026, January 2025 contains 227 games, and every `player_game_logs.ingested_at` falls between 31 May 2026 and 15 Jun 2026 (112,884 rows). A replay that keeps the filter abstains, because none of those rows were "known" in January 2025. That result is the guard, not a failed query.
- Baseline hit rate beats 50% on a held-out month. Not claimed. Kalshi NBA props start in November 2025, so January 2025 has no lines to be "over." A hit rate without a line would be a number I invented.
- The point-in-time regression test passes. That is `test_baseline_db.py`, on top of the existing `test_point_in_time.py`.

PRD section 6.2 also asks for a full posterior, SHAP, and a hybrid-versus-baseline comparison. Those belong to M5 and M6. Shipping them inside M3 would skip the milestones the roadmap ordered.

## Decisions

### One row per player, prop, and game. Lines stay on `markets`.

The PRD asks for one prediction per `(player, prop_type, game)`, with enough information to rebuild a CDF. Kalshi lists several strikes for the same stat. Putting the line on the prediction would either drop strikes or duplicate the forecast.

The row stores mean, std, and the 10/50/90 quantiles of a normal with that mean and std. The normal is not a claim about basketball. It is a stand-in so the row has a band. `docs/CLAUDE.md` says not to issue a prediction without one. M6 replaces the distribution. The payload records `"distribution": "normal"` so a reader does not mistake the quantiles for a fitted posterior.

Rejected: a Bernoulli "over/under" row per strike. That matches the hit-rate metric and throws away the stat forecast the later models are supposed to replace.

### Same model version is written once.

Unique key is `(player_id, game_id, prop_type, model_version)`. A second run of `baseline-m3-v1` skips. A real change bumps the version string, which is `baseline-m3-v1` today.

Rejected: append-only reruns of the same version. The daily job can fire twice. Two rows would force every reader to pick "latest," and a sloppy reader would mix them. The cost is that a bugfix of v1 cannot overwrite v1. That is the point of the version string.

### The clock is 16:00 UTC on the game date.

`prediction_time` is that instant. History must have `event_time < prediction_time` and `ingested_at <= prediction_time`, via the existing `query_player_game_logs` helper. No second filter was written.

16:00 UTC is after the 12:00 UTC box-score ingest and before NBA tip times. The game being forecast has `event_time` at the end of that game date, so it fails `event_time < prediction_time` and cannot enter its own features.

Rejected: using `event_time` itself as the prediction clock. That timestamp is after the game. A stored prediction dated after tip is a lie even if the filter happens to exclude the row.

Rejected: dropping `ingested_at` for historical replays. Bulk loads set `ingested_at` to the fetch time, so a 2025 replay cannot see rows fetched in 2026. That makes January 2025 MAE empty until those rows are treated as known earlier. I did not silently drop the filter to make the report look populated. The report text says this. Changing historical `ingested_at` to "the morning after the game" would be a data migration with its own argument, and it was not done here.

The PRD's backtest sentence says `created_at <= simulated_now`. The schema that actually shipped in M1 uses `event_time` and `ingested_at`. The code follows the schema. Following the PRD's older column name would not match the tables.

### Last 15 games, abstain under 5, half-strength venue and rest effects.

The roadmap says a rolling average over the last 15 games, with home/away and rest-day adjustments. The mean uses only those 15. Home effect is mean(home) minus mean(away) inside that window, applied at half strength. Rest effect is mean(rested) minus mean(back-to-back), also half strength. Both effects are zero unless each bucket has at least 3 games.

Half strength is the part an interviewer should push on. The 15-game mean already mixes home and away. Adding the full venue gap on top double-counts it. Using only same-venue games for the mean would throw away most of a 15-game window. Half is the compromise, not an estimated coefficient. It is not fit on the league, because a coefficient fit on 2024-25 and applied inside 2024-25 would be leakage.

Under 5 games the function returns nothing and the job counts an abstention. A 1-game "average" would still be a stored prediction with a fake band. The roadmap does not name this cutoff. Five is enough to compute a standard deviation and not enough to pretend the player is well estimated. `low_confidence` is true when the window has fewer than 10 games.

The standard deviation is the sample std of the window, floored at 0.5. A player who scored the same number five times would otherwise get a zero band and quantiles glued to the mean. The floor is a numerical guard. The quantiles use the standard normal z values for 10% and 90%, hardcoded so the code does not take a SciPy dependency for a placeholder distribution.

The adjusted mean is clipped at 0. Counting stats cannot be negative. The clip biases the mean in the rare case where the venue adjustment overshoots. `test_counting_stat_is_clipped_at_zero` locks that behavior so it does not become a silent change.

### Home/away uses the previous game's team, not the box score.

There is no roster table. The daily job cannot know tonight's team from a row that does not exist yet. Both the daily job and the replay use the team on the most recent prior game. If that team is not playing tonight, the player is skipped.

Rejected: reading `team_id` off the outcome log during the replay. That is usually the same team, and it is wrong on a same-day trade the model could not have known. The skip is the honest miss.

The replay still uses the box score as the label, and it only scores players who appear in it. MAE is conditional on playing. The baseline does not predict DNPs. The report says so.

### Who gets a forecast.

M3's branch point says Kalshi-covered players, about 50. The loaded `markets` table has 19,736 rows and 148 distinct `player_id` values. The population is those resolved ids. The "about 50" figure in the roadmap is stale relative to the database, and the code follows the database. The alias CSV is gitignored, so the code does not read it.

The daily job is narrower: markets whose `game_id` is today's game. A covered player with no market tonight gets no row. The replay scores every covered player who logged a box score in range, and hit rate only counts lines that exist for that game.

### Hit rate is predicted-over versus actual-over, per line.

Over means `value >= line`. That matches Kalshi "X+" and the `floor_strike` note in the M2 code (`34.5` on a "35+" market still uses `>=` against the stored line). A push on the line counts as over for both sides, so it is a hit. Several strikes for one player-game are several trials. MAE counts the player-prop once, so five strikes do not make one player five times as important in the error.

Rejected: scoring only the strike closest to the mean. That throws away markets the roadmap's hit rate can use, and it chooses the line with information from the prediction itself.

## What I would not defend

- The half-strength coefficients. They are a structural choice, not an estimated effect. If a later month shows the adjustment hurts MAE against the unadjusted mean, the adjustment should be turned off or fit inside the point-in-time window with a real regression. The PRD's phrase "simple regression" is stronger than what shipped. A regression fit once on all seasons was rejected because of leakage. A per-player regression inside the 15-game window is too small to estimate two effects plus a mean. The bucket differences are the regression, degenerate on purpose.
- The normal quantiles. They will look silly for a player whose points are skewed. They exist so the column is not empty.
- `ingested_at` on bulk history. Until that clock is reconciled, the harness cannot produce the January 2025 MAE the roadmap uses as an example, and I will not delete the filter to force it.

## Tests that lock the choices

- `test_baseline.py`: abstain under 5, std floor, half venue gap, clip at 0, 15-game window ignores older games, `>=` line, MAE.
- `test_baseline_db.py`: a 100-point future game does not move a mean of 20. A game that already happened but was ingested after `prediction_time` does not move a mean of 10. The same version does not insert twice. A replay with one line at 22.5, a mean of 20, and an actual of 28 scores a miss and an MAE of 8/3 across the three props.

`uv run pytest -q` on 6 Nov 2026: 76 passed, with local Postgres up. ruff, black, and mypy were clean. Alembic revision `c3b1a9e0d4f2` is applied on that local database.

A one-day replay was run after that:

`uv run python -m app.backtest.run --start 2025-01-15 --end 2025-01-15`

11 games, 148 Kalshi-resolved players, 243 abstentions, 0 forecasts. The players were in the box scores. Their prior games were in the table. The prior games were ingested in May and June 2026, so the 16:00 UTC clock on 15 Jan 2025 could not see them. The report is `docs/results/m3-baseline-2025-01-15-2025-01-15.md`. No prediction rows were inserted.

## Files

- `backend/app/models/baseline.py` holds the arithmetic. No database import.
- `backend/app/models/predict.py` reads history, writes `predictions`, and is the 16:00 UTC job.
- `backend/app/backtest/run.py` is the replay command.
- `db/migrations/versions/c3b1a9e0d4f2_m3_predictions.py` creates the table.
- `backend/app/scheduler.py` registers `daily_predict`. `SCHEDULER_ENABLED` still defaults off.
