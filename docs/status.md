# Status

Checked against the git tree on 6 Nov 2026 (America/New_York). This file is the map a later session can trust. The portfolio story in the README is the target. This file is what the code does.

The original README said the build runs M0 through M10. Milestone writeups for M3–M6 and M8–M10 live in local files that are gitignored (`Roadmap.md`, `PRD.md`, `process.md`, `Reviewer.md`, `CLAUDE.md`, `notebook_notes.md`). They are not in this clone. Anything below that names those milestones is recovered from committed code, ADRs, and a deleted notebook note, and it stops where that evidence stops.

## Where the code is

| Milestone | Evidence | State |
| --- | --- | --- |
| M0 skeleton | FastAPI, Docker Compose Postgres, Alembic, GitHub Actions, Railway config, Next.js app | On `main` |
| M1 NBA box scores and point-in-time schema | Six tables, `LeagueGameLog` loader, daily job, cache, `query_player_game_logs`, failure-mode tests | On `main` |
| M2 Kalshi props | Markets, snapshots, settlements, player aliases, bulk loader, 5-minute snapshot job, ADR-3 | On `origin/kalshi-pipe`, three commits ahead of the old merge base, not on `main` |
| M7 play-by-play | Notebook conclusion: shufinskiy is event data, deferred | Not started. Explicitly out of M1 |
| Modeling, backtest, alerts, HTTP API beyond `/health` | `backend/app/models`, `backtest`, `alerts`, `api` are empty packages | Not started |
| Dashboard views | `frontend/app/page.tsx` is a placeholder | Not started |

## Branches

Fetched from GitHub on 6 Nov 2026. Four branches exist. One of them is the status doc from this session.

| Branch | Tip | What it is |
| --- | --- | --- |
| `main` | `039efd6`, 31 May 2026 | M0 and M1, plus the README that describes the finished product. |
| `m1-start` | `bfcfd84`, 30 May 2026 | Fully merged into `main` as PR #1. No commits of its own remain. The tip commit deletes `notebooks/notebook_notes.md` and `backend/tests/test_spot_check.py`. |
| `kalshi-pipe` | `c65c419`, 15 Jun 2026, 3:54 PM ET | The only unmerged work. Three commits: Kalshi ingestion (`221cc5f`, 31 May), alias auto-match plus a `PlayIn` season-type choice (`7d746df`, 15 Jun), then the M2 migration, ADR-3, and a gitignore change (`c65c419`, 15 Jun). |
| `cursor/project-status-fb24` | this status writeup | Documentation. Not product code. |

`kalshi-pipe` branched from `072cf9f` (the "finished portfolio" README). `main` then added two more README commits, so the histories diverged by those README edits on one side and the Kalshi commits on the other.

The last `kalshi-pipe` commit appends `adr.md` and `docs/` to `.gitignore`. `docs/adr.md` stayed in git only because it was already tracked. A later `git add` of a new file under `docs/` would silently skip it. Landing M2 means taking the Kalshi code and dropping those two ignore lines.

`kalshi-pipe` also changes shared M1 code, not just new files: the HTTP cache retries HTTP 429 (Kalshi rate limits) with the same backoff as timeouts, and `bulk_load --season-type` accepts `PlayIn` alongside `Regular Season` and `Playoffs`. The daily job is still regular season only.

## What M1 actually contains

- Tables: `players`, `teams`, `games`, `game_results`, `player_game_logs`, `request_cache`.
- Fact tables carry `event_time` and `ingested_at`. The only historical helper is `query_player_game_logs`, and it requires `as_of`.
- `event_time` for a game is next-day midnight UTC after `GAME_DATE`. LeagueGameLog has no tip time. `ingested_at` is the real leak guard.
- Bulk load: `uv run python -m app.data.bulk_load --start 2022-23 --end 2024-25` from `backend/`.
- Daily job: 12:00 UTC, yesterday's regular season, only if `SCHEDULER_ENABLED=true`.
- HTTP client is `curl_cffi` impersonating Chrome 120, because `stats.nba.com` drops normal Python TLS. ADR-2.
- Tests cover parsers, cache failure modes (timeout, 429, bad JSON, schema drift), the daily season cutoff, and point-in-time filtering. DB tests skip when Postgres is down. A skipped DB suite is not a green M1.
- `spot_check` prints box scores. Its test file was deleted in `bfcfd84`. A manual Basketball Reference check after a real load is still outstanding. Nothing in git records that the check happened.

## What M2 contains on `kalshi-pipe`

- Migration `124f1a7e317d` adds `markets`, `market_snapshots`, `market_settlements`, `kalshi_player_aliases`.
- Series in scope: `KXNBAPTS`, `KXNBAREB`, `KXNBAAST`. Other series raise.
- Public REST only: `https://api.elections.kalshi.com/trade-api/v2/markets`. No auth, no trading.
- Settled history loader: `python -m app.data.kalshi_bulk_load --min-close-date ... --max-close-date ...`. Snapshots are a separate 5-minute job.
- ADR-3 says Kalshi's REST gives settlements and the current book, and does not give the price path from before this system started polling. A backtest can score a model against outcomes. It cannot reconstruct what the market quoted last winter unless a candlestick or trade endpoint is added later.
- Alias resolution is a CSV seed plus a name auto-match. The seeder reads `backend/app/data/kalshi_player_aliases.csv`. That file is not in git. `*.csv` is gitignored, so a commit of the seed file needs a negation rule.
- There is still no `as_of` helper for snapshots. ADR-3 describes the query. `queries.py` only has the player-log helper.
- ADR-3's status line says it was drafted 2026-05-31 for Ronnie to rewrite in his own voice.

About 65 tests on that branch, 26 on `main`. Counts from `def test_`.

## What is not in the repo

- No XGBoost, PyMC, or ArviZ dependency. `pyproject.toml` does list `anthropic`, and no module calls it.
- No injury parser, no news ingestion, no lineup redistribution.
- No feature matrix, no trained artifact, no backtest runner, no calibration table.
- No route except `GET /health`.
- Frontend dependencies are Next, React, and TanStack Query. No Recharts.
- `SCHEDULER_ENABLED` defaults off. The scheduler registers the daily NBA job. On `kalshi-pipe` it also registers the 5-minute Kalshi job.

## Deploys, checked 6 Nov 2026

- https://nba-alpha-prop.vercel.app returns the placeholder page.
- https://gregarious-friendship-production-b0f6.up.railway.app/health returns Railway's "Application not found". The FastAPI service named in the old README is gone. `railway.json` is still in the repo for a later deploy.
- This cloud environment had no Docker and no `uv` at inspection time. There is no `.cursor/environment.json`.

## Ownership that should stay with Ronnie

A deleted notebook note (`notebooks/notebook_notes.md`, removed in `bfcfd84`) said schema reasoning, ADR prose, and the point-in-time regression test stay personally owned, and boilerplate can be delegated. Later sessions should implement a decision that is already written down. A new accepted ADR is Ronnie's to phrase.

## Local run

```bash
docker compose up postgres -d
cp .env.example .env
cd backend
uv sync
uv run alembic upgrade head
uv run pytest
```

Postgres in Compose is `nba:nba@localhost:5432/nba_alpha_prop`. That URL is a local default, not a secret.
