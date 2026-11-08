# available_at

## What this is for

M5 in `docs/Roadmap.md` stays open until a holdout exists where both clocks pass and the history is newer than 14 days. The acceptance line in `docs/provenance/m5-plan.md` is: on that holdout, XGBoost MAE is lower than the baseline on the same player-props, and the holdout is more than one game. Under `ingested_at` the only contract-bearing night with any history was 3 June 2026, and that history ended the previous season. This change is the clock that makes a later comparison possible. It does not fit a booster.

## The choice

`available_at` is a required timestamp on `player_game_logs` and `game_results`. For a bulk load it is 12:00 UTC on the calendar day after `games.game_date`. For a live daily fetch it is the same instant as `ingested_at`. `query_player_game_logs` returns a row when `event_time` is before `as_of` and `available_at` is at or before `as_of`. `ingested_at` stays the fetch time and is not the feature filter. Market quotes still need `quoted_at` and `ingested_at` at or before the clock.

Rejected: rewriting `ingested_at` on the bulk rows. That column is the audit of when the file was fetched. A 31 May 2026 fetch of a January 2025 game would then look like a January fetch.

Rejected: a flag that ignores `ingested_at` on feature reads. The next caller can forget the flag and the leak comes back. The column is the rule.

Rejected: putting the same morning-after stamp on `games`. The schedule is knowable before the box score. Quotes, settlements, and predictions do not get the column.

## What would show the choice is wrong

The stamp is the morning after the printed `game_date`, not the first time a box score was published, and not a later correction. If a stat correction lands days afterward and the row's `available_at` is still the next noon, a backtest treats the corrected number as known the next morning. A second `player_game_logs` row whose `available_at` is the correction time, scored against the first row, would show that. That path is not built. Bulk load still skips a `(player_id, game_id)` it has already stored, so a re-fetch does not update `available_at`.

A game whose box score does not exist by 12:00 UTC the next day would be marked known too early. The daily job was not run against the API in this change, so that case was not observed.

## What the local database did

Migration `b7c2e9a41d08` (revises `c3b1a9e0d4f2`) added the column nullable, backfilled from `games.game_date`, then set it not null, and added `ix_pgl_player_event_available`. After `alembic upgrade head` on local Postgres: 112,884 player logs and 5,279 game results, zero nulls. One 15 January 2025 log is `available_at` 16 January 2025 12:00 UTC and `ingested_at` 31 May 2026 00:58 UTC.

`uv run mypy app tests` reported no issues. `uv run pytest -q` reported 93 passed.

The June replay, command `uv run python -m app.backtest.run --start 2026-06-03 --end 2026-06-13`, wrote `docs/results/m4-calibration-2026-06-03-2026-06-13.md`. Copied from that run: 5 games, 180 forecasts, 0 invisible, 0 short windows, MAE 2.953 on 180, hit rate 84/108 agreement, predicted over 29/42, predicted under 55/66, one scored date (2026-06-03), history gaps 4 to 9 days, Brier 0.157574 on 108 contracts, log loss 0.472966, calibration error 0.100292, 0 quotes. The previous report under `ingested_at` was 168 forecasts, gaps 416 to 476, Brier 0.177592 on 105 contracts.

The November replay, `--start 2025-11-01 --end 2025-11-30`, wrote `docs/results/m4-calibration-2025-11-01-2025-11-30.md`. Copied from that run: 219 games, 5151 forecasts, 0 invisible, 0 short windows, 6 skipped because the prior team was not in the game, MAE 3.208 on 5151, 0 contracts, Brier not scored. The previous report was 5157 invisible player-props and 0 forecasts. There are still no November markets. The MAE is box-score error with no line.

## The stored rows and the report

`store_forecast` skips a `(player, game, prop, baseline-m3-v1)` it has already written. The report scores the forecast it just computed, not the stored row. After these two replays the table has 5,331 `baseline-m3-v1` rows: 168 written on 6 November under `ingested_at`, and 5,163 written on 7 November under `available_at`. Of the Finals rows, 60 still have `payload.rest_days` of 400 or more. Those are the old 3 June and 5 June keys. The June report's 4-to-9-day gap is the recomputed forecast. It is not what those 60 rows contain. The version was not bumped and the old rows were not deleted.

## What was not verified

The daily job's `availability="observed"` branch was not executed against stats.nba.com. No new bulk season was fetched. Quote behavior was not changed: both replays still report 0 mids. CI was not run with `DATABASE_URL` unset, so the leak tests that need Postgres are still the local run. ADR-3 was not edited.
