# M8 plan: forecasting dashboard

Written 27 Nov 2026, before implementation. Results after the proving
commands land in `docs/provenance/m8-dashboard.md`.

## Where this aims

Revised acceptance for this milestone (not the raw Roadmap "edges /
production URL" lines):

- Three core views work: today comparisons, player detail, calibration.
- Mobile layout works (narrow viewport).
- FCP under about 2 seconds on a local production Next build against a
  warm API, noted in the results note.
- No edge or EV copy in the UI or in product-facing API field names
  (`gap` / `disagreement`).
- Railway / public API URL left open for later.

## Decisions

### Model vs market gap, not edge.

Today's table shows player, prop, line, model probability, market mid,
and signed gap (`model_p - mid`). That reuses the M4 disagreement
framing. Rejected: shipping "edge" or +EV language in M8.

### Slate API, not tip clock.

Endpoints take an optional date and default to the latest game date that
has predictions and markets. Rejected: blocking M8 on pre-tip `Game`
ingest.

### Display version preference.

For each `(player, game, prop)` pick the first of `lineup-m7-v1`,
`pymc-m6-v1`, `xgb-m5-v1`, `baseline-m3-v1`. Label the version.

### Deploy is out.

Railway stays deferred. Close on local FastAPI + Next with CORS.
Vercel may keep pointing at a placeholder.

### System status is in. Backtest replay is out.

A small `/status` page shows freshness and registered job ids.

### Charts use stored mean and std.

Density for player detail is a normal from the prediction row. NetCDF
draws stay gitignored and are not required for the chart.

## What would make this plan wrong

- No date with both predictions and mids leaves today empty with no
  date picker escape.
- Huge comparison payloads break the FCP bar.
- Product copy slips back into edge or EV wording.
