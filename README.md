# NBA Player Props, Forecast Honestly

**Backend health:** https://gregarious-friendship-production-b0f6.up.railway.app/health

I built a system that watches NBA player prop markets on Kalshi, forecasts how many points, rebounds, and assists each player will actually get, and flags the cases where the market price disagrees with the forecast in an interesting way.

> This is a portfolio project, not a betting tool. No real money moves through it. The point is to demonstrate engineering and modeling judgment end-to-end.
## What the dashboard shows

Three views. Plain English version below.

**Today's edges.** A ranked list of player prop bets where my model and the market disagree the most, with a confidence indicator next to each one. Sorted so the most interesting ones are on top.

**Player drill-down.** Click a player, see a chart of the model's full belief about how they'll perform tonight: not a single number, but a probability spread. You can see where the market's line falls on that spread.

**Calibration.** The most honest view in the app. It tracks how the model has actually performed over time. When I said something would happen 70% of the time, does it actually happen 70% of the time? If not, by how much am I off? Most prediction systems hide this.


## Why I built it

The honest answer to "why NBA props" is that I can train a model on real data, compare it to a real market price every day, and find out within hours whether my prediction was right. 

## How the forecasting works (intuition, no math)

There are two layers stacked on top of each other.

The first layer is a **gradient-boosted tree model**. It takes everything I know about a player and tonight's game (rolling averages over different windows, the opponent's defense, pace, home or away, rest days, recent usage, who else is on the floor) and produces a number. That number is the model's best single-point guess at how many points the player will score.

The second layer is a **hierarchical Bayesian model**. This layer does a lot for calibration. Three things it does that the tree alone cant:

1. **It produces a distribution, not a number.** Instead of "I think LeBron will score 28," it says "I think LeBron will score somewhere in this range, with this shape." That's what lets me compare to a market price honestly. Markets price probabilities, not point estimates.
2. **It borrows strength across similar players.** A rookie with five games of data doesn't get an overfit projection. The model pools information from other players who fit the same profile.
3. **It updates cleanly when news lands.** When a star is ruled out, usage and minutes redistribute among teammates in specific ways. The Bayesian layer treats this as a prior update. Tree-based models would have to retrain from scratch.

Together: the trees do the feature-rich heavy lifting, the Bayesian layer wraps it in calibrated uncertainty.

## Where the injury news comes in

I run an LLM (Claude Haiku) over official NBA injury reports and breaking news from ESPN and Bleacher Report. The LLM doesn't predict anything. Its job is small and bounded: read a news item and extract structured fields. Player name. Injury severity. Expected games missed. Source reliability. Confidence.

Those structured fields flow into the model as prior updates on the affected players. So when news breaks that a starter is out, the model's projections for his teammates shift in the right direction within minutes, not the next day.

## Under the hood car emoji later

- **Backend:** Python, FastAPI, PostgreSQL, SQLModel, Alembic migrations.
- **Modeling:** XGBoost (point predictor), PyMC (Bayesian wrapper), arviz (posterior analysis).
- **Frontend:** Next.js 14, TypeScript, Tailwind, TanStack Query, Recharts.
- **Data sources:** stats.nba.com (box scores), Kalshi public API (prop markets), nbainjuries package + ESPN/Bleacher Report RSS (injuries).
- **LLM:** Anthropic Claude Haiku for injury classification, structured JSON output.
- **Scheduling:** APScheduler running inside the FastAPI process.
- **Deployment:** Railway for the backend and Postgres, Vercel for the frontend, GitHub Actions for CI.

Total monthly hosting cost stays under $25. No paid data feeds.

## What this is not

- Not a betting tool. No real trades. No execution.
- Not a "beat the market" system. The Kalshi market is competitive. The goal is to be calibrated and honest, not to claim alpha.
- Not feature-complete. Three prop types, fifty-ish players, NBA only. Expanding scope is a v2 conversation.
- Not a finished research result. It's a working pipeline with documented calibration. That's the artifact.

## Repo layout

```
backend/      FastAPI app, data ingestion, model code, backtests
frontend/     Next.js dashboard
db/           Alembic migrations
docs/         Architecture decisions, results, model card
```

## License

MIT.

## About me

I'm Ronnie. I built this between coursework as an undergrad. Happy to walk through any part of it. Reach me at wronnie@seas.upenn.edu
