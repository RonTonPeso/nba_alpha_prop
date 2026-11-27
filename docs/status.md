# Status

Checked against the git tree on 27 Nov 2026 (America/New_York). This file is the map a later session can trust. The portfolio story in the README is the target. This file is what the code does.

## Where the code is

| Milestone | Evidence | State |
| --- | --- | --- |
| M0 skeleton | FastAPI, Docker Compose Postgres, Alembic, GitHub Actions, Railway config, Next.js app | On `main` |
| M1 NBA box scores and point-in-time schema | Six tables, `LeagueGameLog` loader, daily job, cache, `query_player_game_logs`, failure-mode tests | On `main` |
| M2 Kalshi props | Markets, snapshots, settlements, aliases, bulk loader, 5-minute snapshot job, ADR-3 | On `main` |
| M3 baseline | `baseline-m3-v1` predictions, daily predict job | On `main` |
| M4 calibration | Backtest Brier / calibration report | On `main` |
| M5 XGBoost | `xgb-m5-v1`, ten box-score features, SHAP payload | On `main` |
| M6 posterior | `pymc-m6-v1` for points, rebounds, assists; ADR-4 | On `main` |
| M7 injury + lineup | `injury_signals`, `started` backfill, Haiku classifier, `lineup-m7-v1`, ADR-5 | On `m7-injury` |
| M8 dashboard | Placeholder frontend | Not started |
| M9–M10 | Alerts / polish | Not started |

## M7 on `m7-injury`

- Migration `d4e8f2a61b09`: `injury_signals` table; `player_game_logs.started`.
- Starter backfill: `python -m app.data.starter_backfill` via `boxscoretraditionalv2` `START_POSITION`.
- Injury pipeline: `python -m app.data.injury.run --timed` (ESPN RSS + optional official/`nbainjuries` + BR sitewide feed filtered for NBA).
- Classifier: Claude Haiku 4.5, prompt `m7-injury-v1`. Held-out joint accuracy 1.000 on 100 (`docs/results/m7-llm.md`).
- Lineup effects: `models/lineup_m7_effects.json`. Embiid→Maxey points delta +3.27. Synthetic test and a stored `lineup-m7-v1` Maxey row.
- Scheduler registers `injury_official` (hourly) and `injury_rss` (15 min). `SCHEDULER_ENABLED` still defaults false.
- Provenance: `docs/provenance/m7-plan.md`, `docs/provenance/m7-injury.md`. ADR-5 in `docs/adr.md`.

## What is still out of scope after M7

- No Twitter / X injury monitoring.
- Daily production path still writes `baseline-m3-v1` before tip; injury-aware rows are additive.
- League-wide starter backfill beyond PHI is optional follow-up.
- `nbainjuries` needs a working JVM on this laptop; RSS proved the 5-minute path.
- No edges / EV language.
- Dashboard (M8) not started.

## Local run

```bash
cp .env.example .env   # DATABASE_URL, ANTHROPIC_API_KEY
cd backend && uv sync && uv run alembic upgrade head
uv run python -m app.data.injury.run --timed
uv run python -m app.models.lineup_fit
uv run python -m app.models.lineup_apply --synthetic-embiid-maxey
```
