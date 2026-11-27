# Model card

## Model name

`nba_alpha_prop` forecasting stack: `baseline-m3-v1`, `xgb-m5-v1`,
`pymc-m6-v1`, `lineup-m7-v1`.

## Intended use

Personal portfolio system for NBA player prop **forecasting** and
**market comparison**. It produces a probability that a counting stat
meets or exceeds a Kalshi line, and shows the gap versus the market mid.
It is not a product for placing wagers.

## Inputs

- Historical and daily NBA box scores (`LeagueGameLog`, starter flags
  from traditional box scores)
- Kalshi public market metadata, snapshots, and settlements
- Classified injury claims (Haiku over official reports / RSS)

All feature reads respect point-in-time clocks
(`event_time` / `available_at` for box scores and injury signals;
`quoted_at` / `ingested_at` for quotes).

## Outputs

Per `(player, game, prop, model_version)`:

- Mean, std, and quantiles of a normal (or posterior summary)
- Dashboard: P(stat ≥ line), market mid, signed gap
- Optional SHAP top-5 on XGBoost rows
- Optional lineup adjustments when a starter is out

## Training and evaluation data

- Box scores from the seasons loaded into the local / Railway database
  (bulk load from 2022–23 onward in this project)
- Holdouts and Briers documented under `docs/results/` (M4 calibration,
  M5 XGBoost, M6 posteriors)
- Lineup effects fit on starter-flagged PHI history for the Embiid→Maxey
  acceptance cell; artifact `models/lineup_m7_effects.json`

## Metrics that matter here

- MAE of the mean versus realized stat (headline rest ≤ 14 days for M5)
- Brier of P(stat ≥ line) versus 0/1 outcomes
- Calibration bins and calibration error (M4 report)
- Disagreement hit rate when a mid exists (count of sides, not payout)

## Limitations

- Daily production writes are still `baseline-m3-v1`. Richer versions are
  shown when stored rows exist.
- Pre-tip `Game` rows are incomplete; the dashboard is slate-based.
- Density charts use stored mean/std, not full NetCDF draws.
- Injury official PDF path needs a working JVM; RSS covers the pipeline.
- Starter backfill for lineup training was PHI-first for M7 close.
- No claim that gap equals edge, EV, or a recommended bet.

## Ethical / misuse notes

Do not use outputs as financial advice. Kalshi markets are shown for
comparison and calibration study. The repo may be private; treat API
keys and database URLs as secrets even so.
