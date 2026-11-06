# NBA Player Props, Forecast Honestly

**Frontend placeholder:** https://nba-alpha-prop.vercel.app

This repo is a forecasting system for NBA player props. The target is a hierarchical Bayesian model wrapped around a gradient-boosted feature predictor, producing a distribution over points, rebounds, and assists, then set next to Kalshi's price for the same prop. The dashboard's job is to show the disagreement and, on a separate screen, whether the probabilities have been calibrated.

This is a portfolio project. No real money moves through it. The point is the engineering and the modeling judgment, end to end.

**Where the code is today:** M0 and M1 are on `main`. M2 (Kalshi ingestion) is implemented on `kalshi-pipe` and is not merged. The model, the backtest, the injury parser, and the three dashboard views are not built. `docs/status.md` is the detailed map. The paragraphs below describe the product being built.

The old Railway health URL (`gregarious-friendship-production-b0f6.up.railway.app`) returned "Application not found" when checked on 6 Nov 2026. The service is not up. `railway.json` is still the deploy config for whenever it comes back.

## What the dashboard is for

Three views.

**Today's slate.** A ranked list of player props where the model and the market disagree, with a confidence indicator, most interesting first.

**Player drill-down.** One player, one chart of the model's full belief about tonight: a probability spread, with the market's line marked on it.

**Calibration.** When the model said 70%, how often it happened. This is the view the project is willing to be judged on.

## How the forecast is designed

Two layers.

The first is a gradient-boosted tree. It takes what is known about the player and the game before tip (rolling averages, opponent defense, pace, home or away, rest, recent usage, who else is on the floor) and produces a point estimate for the stat.

The second is a hierarchical Bayesian model around that estimate. It does three things the tree does not:

1. It produces a distribution, so a market price can be compared to a probability.
2. It pools players with a similar profile, so a rookie with a handful of games does not get an overfit projection.
3. It can take a news update as a change to the prior. A starter ruled out moves teammates' minutes and usage without a full retrain.

The tree does the feature work. The Bayesian layer carries the uncertainty. Neither layer is in the code yet. `backend/app/models/` is empty, and `pyproject.toml` does not depend on XGBoost, PyMC, or ArviZ.

## Where injury news fits

The design uses Claude Haiku on official NBA injury reports and on ESPN and Bleacher Report items. The model call extracts fields: player, severity, expected games missed, source, confidence. Those fields are prior updates. There is no injury module yet. The `anthropic` dependency is declared and unused.

## Stack

- **Backend:** Python, FastAPI, PostgreSQL, SQLModel, Alembic. These are in the repo and tested.
- **Data in the repo:** `stats.nba.com` box scores through `LeagueGameLog`, cached in Postgres, fetched with `curl_cffi` so Akamai accepts the TLS handshake. Kalshi's public market API is coded on `kalshi-pipe`.
- **Modeling, still ahead:** XGBoost, PyMC, ArviZ.
- **Frontend:** Next.js 16, TypeScript, Tailwind, TanStack Query. Recharts is the chart library to add with the first real view.
- **Scheduling:** APScheduler inside the FastAPI process. The daily NBA job exists. It runs only when `SCHEDULER_ENABLED=true`.
- **Deploy target:** Railway for the API and Postgres, Vercel for the frontend, GitHub Actions for lint, types, and tests.

Hosting stays on free public data. No paid stats feed.

## What is running

From `backend/`, with Postgres up and `DATABASE_URL` set (see `.env.example`):

```bash
uv sync
uv run alembic upgrade head
uv run pytest
uv run python -m app.data.bulk_load --start 2024-25 --end 2024-25
uv run python -m app.data.spot_check --n 3
uv run uvicorn app.main:app --reload
```

`GET /health` returns `{"status":"ok"}`. The bulk loader and the spot check need a migrated database. Tests that need Postgres skip when it is down, so a green run without Postgres has not exercised the database.

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

## Repo layout

```text
backend/      FastAPI app, NBA ingestion, and the empty model, backtest, alerts, and api packages
frontend/     Next.js app, currently a placeholder page
db/           Alembic migrations
docs/         ADRs, status, and the plan for the next build session
notebooks/    One shufinskiy exploration notebook
```

## Scope boundaries

- No order entry and no real trades.
- The Kalshi market is the comparison point. The project keeps score on calibration.
- Three prop types, on the order of fifty players, NBA only, until a later version says otherwise.
- The artifact to aim at is a working pipeline plus a calibration report.

## License

MIT.

## About me

I'm Ronnie. I built this between coursework as an undergrad. Happy to walk through any part of it. Reach me at wronnie@seas.upenn.edu
