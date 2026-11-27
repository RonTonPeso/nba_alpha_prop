# M8 results: forecasting dashboard

Written 27 Nov 2026 after the proving commands. The plan is
`docs/provenance/m8-plan.md`.

## Acceptance aimed at

- Three core views work: today comparisons, player detail, calibration.
- Mobile layout works (narrow viewport cards on Today).
- FCP under about 2 seconds on a local production Next build against a
  warm API.
- No edge or EV product language (`gap` / `disagreement`).
- Railway / public API URL left open.

## Commands run

```bash
cd backend
uv run pytest tests/test_api_dashboard.py -q
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

cd ../frontend
npm install   # adds recharts
npm run build
npm run start -- -p 3000
```

API smoke:

```bash
curl -s 'http://127.0.0.1:8000/api/comparisons/today'
curl -s 'http://127.0.0.1:8000/api/calibration/summary'
curl -s 'http://127.0.0.1:8000/api/status'
curl -s 'http://127.0.0.1:8000/api/players/1630178/detail?prop_type=points'
```

## Evidence

### API

- `GET /api/comparisons/today` on the local DB returned date `2026-06-03`,
  100 rows (limit), first row Karl-Anthony Towns. Warm TTFB about 0.08s.
- Calibration summary parsed M4 bins and M5/M6 prop Briers from
  `docs/results/`.
- Status reports `api_version=m8-dashboard` and five registered job ids;
  `SCHEDULER_ENABLED` false.
- Player detail for Maxey preferred `lineup-m7-v1`, mean 28.46, 60
  density points. Density is the stored normal, not NetCDF draws.
- `tests/test_api_dashboard.py`: 4 passed.
- Product fields use `gap` / `market_mid` / `model_p`. No `edge` key.

### Frontend

- `next build` succeeded (routes `/`, `/calibration`, `/status`,
  `/players/[id]`).
- Production `next start` on port 3000: document TTFB about 1–2 ms on
  localhost after warm. Combined with warm API (~80 ms for today), shell
  plus first data paint stays under the 2s local bar.
- Today has desktop table and mobile stacked cards, loading/empty/error
  states, slate date picker. Calibration and status pages wired through
  TanStack Query (5-minute staleTime).

### Not verified

- Railway / public production API URL (deferred by plan).
- Browser Lighthouse FCP on a non-localhost network.
- Visual QA on a physical phone (layout is responsive CSS only).

## Decisions that held

Model vs market gap naming. Slate date default. Version preference
lineup → pymc → xgb → baseline. Deploy out of milestone.
