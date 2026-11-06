# Next session

One cloud agent, one branch, three checkpoints, in this order. The morning review is the branch. Do not open a pull request unless asked.

Create the branch from `cursor/project-status-fb24` if that branch exists, otherwise from `main` after this status doc is on `main`. Branch name: `cursor/overnight-m2-baseline-fb24`.

Commit at the end of each checkpoint with a message that names the checkpoint. Push the branch after the last checkpoint you actually finish. If a checkpoint is blocked, write the blocker in `docs/overnight-log.md` and continue only with work that does not depend on the blocker.

## Rules for the whole session

- Read `docs/status.md` and `docs/adr.md` before editing. On the Kalshi work, also read ADR-3 from `origin/kalshi-pipe:docs/adr.md`.
- If the prompt includes a pasted `Roadmap.md` or `PRD.md` and it conflicts with this file, stop checkpoint 3, follow the pasted spec, and record the conflict in `docs/overnight-log.md`.
- Do not push to `main`. Do not write to Railway. Do not use a `DATABASE_URL` that points anywhere but local Postgres started in this environment.
- Do not add XGBoost, PyMC, ArviZ, or any Anthropic call. `anthropic` may stay in `pyproject.toml` untouched.
- Do not write or rewrite an accepted ADR. ADR-3 stays in Ronnie's voice, including the line that says he still needs to rewrite it.
- Do not invent Kalshi player-id mappings. Report unmapped names.
- Do not describe the baseline as an edge, a positive-EV bet, or a Bayesian posterior.
- Historical reads take an `as_of` and filter `event_time` and `ingested_at`. Follow `query_player_game_logs`.
- `uv run pytest` with Postgres unavailable is a failed checkpoint. The DB tests skip in that case, and a skip is not a pass. Start Postgres first.
- Install `uv` and Postgres in the environment if they are missing. Docker is fine. A local Postgres on port 5432 with the `.env.example` URL is fine.
- Leave `SCHEDULER_ENABLED` unset. Call the loaders once by hand. Do not start a 5-minute poll loop.
- Keep the diff limited to the checkpoint you are in.

## Checkpoint 1 — Land M2

Bring `origin/kalshi-pipe` onto this branch.

- Take the Kalshi modules, tests, migration `124f1a7e317d`, scheduler job, table changes, ADR-3, the 429 retry in `CachedHttpClient`, and the `PlayIn` season-type choice.
- Do not take the two lines `kalshi-pipe` added at the bottom of `.gitignore` (`adr.md` and `docs/`). Those would hide new files in `docs/`, including the overnight log. `docs/adr.md` is already tracked; leave it tracked.
- `m1-start` is already merged into `main`. Do not revive it.
- Keep the README, `docs/status.md`, and `docs/adr-template.md` from this branch. `main` and `kalshi-pipe` both edited `docs/adr.md`; the result should contain ADR-1, ADR-2, and ADR-3, with the template staying in its own file.
- Fix only mechanical rebase breakage.
- `*.csv` is gitignored, so `kalshi_player_aliases.csv` cannot be committed until a negation is added. Do not add a negation, and do not create a fake CSV. Note the missing file in `docs/overnight-log.md`.
- Run, from `backend/`: `uv run ruff check .`, `uv run black --check .`, `uv run mypy app tests`, `uv run pytest`. All of them pass, including the Kalshi tests and the M1 tests.
- Update the M2 row in `docs/status.md` to say it is on this branch.

Done when those four commands pass and the log names the commit.

## Checkpoint 2 — Prove a real load

Use the local database only.

1. `uv run alembic upgrade head` from `backend/` so both migrations are applied.
2. One NBA probe before a season load. Call the existing LeagueGameLog path for a single past date in the 2024-25 regular season. If `stats.nba.com` times out, returns 403, or the TLS impersonation fails, stop the NBA load. Write the exception and the command into `docs/overnight-log.md`. Do not insert synthetic NBA rows.
3. If the probe returns rows, load the 2024-25 regular season only: `uv run python -m app.data.bulk_load --start 2024-25 --end 2024-25`. Record the season summary (teams, players, games, player_game_logs, errors).
4. Run `uv run python -m app.data.spot_check --n 3 --seed 7`. Paste the text into the log. If a public box score can be fetched for one of those games, say whether points, rebounds, assists, and minutes match. If the page is blocked, say that the printout is unchecked.
5. Kalshi probe: one 7-day window, not the full history. Example: `--min-close-date 2025-11-01 --max-close-date 2025-11-07`. If the host is blocked, log it and stop the Kalshi load. If it runs, record markets seen, inserted, settlements, players unmapped, games unmapped, and the unmapped player names. Unmapped games are expected when the NBA season in the database does not cover that date. That is a finding, not a bug to paper over.
6. Do not commit database dumps, cache bodies, or CSV extracts of the tables. The log's counts are the artifact.

Done when the log has either real counts or a specific network error for each source.

## Checkpoint 3 — Baseline, with the leak test

Build a small, honest baseline on top of M1. This is the stand-in until the hierarchical model exists. It is a frequency, not a forecast model.

Behavior, locked:

- Props: points, rebounds, assists, read from `PlayerGameLog.points`, `.rebounds`, `.assists`.
- A Yes outcome means `stat >= line`. That matches ADR-3's reading of Kalshi "X+" markets. If a real `rules_primary` string from checkpoint 2 says otherwise, stop and log the sentence instead of guessing.
- History is the last 20 regular-season games from `query_player_game_logs` at the supplied `as_of`. Playoffs stay out.
- Fewer than 5 games returns no probability and the reason `short_history`.
- Probability is `count(stat >= line) / n`.
- For a historical game, `as_of` is that game's `event_time`, so the game itself is excluded by `event_time < as_of`.

Tests, in `backend/tests/`, using the existing DB fixture:

- A game with `event_time` before `as_of` and `ingested_at` after `as_of` does not change the probability.
- The game being scored is not inside its own history.
- `stat == line` counts as a hit.
- Four prior games abstain. Five prior games return a probability.
- A pure function computes Brier score and 0.1 calibration buckets from a list of `(probability, outcome)` pairs. Cover an empty list and a single bucket.

CLI, from `backend/`:

```bash
uv run python -m app.backtest.baseline --season 2024-25
```

It walks player-games in that season, scores the baseline, and prints JSON with sample size, abstentions, Brier score, and the buckets. If the season has no rows, exit code 2 and a JSON body that says the table is empty. Do not commit a report unless this command produced it. If it produced one, write `docs/baseline-report.json` and cite the command and the row count in `docs/overnight-log.md`.

HTTP: add `GET /baseline/report`. It returns the JSON file when present, and a clear empty payload when the file is absent. `/health` stays.

Frontend: keep the current page. Under the existing sentence, render the report when `frontend/public/baseline-report.json` exists (copy the docs file only after a real run). When the file is absent, the page still says the app is under construction and adds one line that the baseline report has not been generated. No "edge", "EV", or "posterior" copy. `npm run lint` and `npm run build` pass.

Do not join Kalshi prices into the probability. Settlements may be counted in the log as a side note (how many joined rows existed). The score is against box-score outcomes.

Done when the new tests pass with the rest of pytest, the CLI behaves on both an empty and a non-empty database, and the frontend build passes.

## After the three checkpoints

Stop. Do not start injury classification, XGBoost, PyMC, lineup features, or a dashboard of recommended bets. Leave a short "left for Ronnie" list in `docs/overnight-log.md`: unmapped names, whether the NBA and Kalshi hosts answered, whether ADR-3 still needs his pass, and the Railway service still being absent.
