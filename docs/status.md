# Status

Checked against the local tree on 27 Nov 2026 (America/New_York). The README
is the short product story. This file is what the code does.

## Where the code is

| Milestone | Evidence | State |
| --- | --- | --- |
| M0 skeleton | FastAPI, Docker Compose Postgres, Alembic, CI, Railway, Next | On `main` |
| M1–M7 | Box scores, Kalshi, baseline, calibration, XGBoost, posteriors, injury + lineup | On `main` |
| M8 dashboard | Comparison / detail / calibration / status API + Next views | On `main` |
| M9 alerts | Discord webhooks | Not started (optional) |
| M10 polish | README, architecture, model card, screenshots, UI pass, secrets check | In progress on `m10-polish` |

## Dashboard (M8)

- API: `GET /api/comparisons/today`, `/api/comparisons/dates`,
  `/api/players/{id}/detail`, `/api/calibration/summary`, `/api/status`
- Language is model vs market **gap**, not edge or EV
- Frontend: TanStack Query, Recharts, slate-date picker, player density
- `NEXT_PUBLIC_API_BASE_URL` defaults to `http://127.0.0.1:8000`
- Provenance: `docs/provenance/m8-plan.md`, `m8-dashboard.md`

## Local run

```bash
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

Open http://127.0.0.1:3000 with the API on 8000.

## Still open after M10

- Discord alerts (M9), if you want them
- Flipping daily predict off `baseline-m3-v1`
- Pre-tip schedule ingest (dashboard remains slate-based)
- Public Railway / Vercel URLs staying warm is ops, not a code gap
