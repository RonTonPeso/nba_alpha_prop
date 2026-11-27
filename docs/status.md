# Status

Checked against the git tree on 27 Nov 2026 (America/New_York). This file is the map a later session can trust. The portfolio story in the README is the target. This file is what the code does.

## Where the code is

| Milestone | Evidence | State |
| --- | --- | --- |
| M0 skeleton | FastAPI, Docker Compose Postgres, Alembic, GitHub Actions, Railway config, Next.js app | On `main` |
| M1–M7 | Box scores, Kalshi, baseline, calibration, XGBoost, posteriors, injury + lineup | On `main` |
| M8 dashboard | FastAPI comparison/detail/calibration/status routes; Next Today / player / calibration / status | On `m8-dashboard` |
| M9 alerts | Discord webhooks | Not started |
| M10 polish | README / model card / Railway | Not started |

## M8 on `m8-dashboard`

- API: `GET /api/comparisons/today`, `/api/comparisons/dates`, `/api/players/{id}/detail`, `/api/calibration/summary`, `/api/status`.
- Language is model vs market **gap**, not edge or EV.
- Frontend: TanStack Query (5 min stale), Recharts density + calibration chart, mobile cards on Today.
- CORS for local Next. `NEXT_PUBLIC_API_BASE_URL` defaults to `http://127.0.0.1:8000`.
- Railway / public API URL deferred. Provenance: `docs/provenance/m8-plan.md`, `m8-dashboard.md`.

## Local run

```bash
# API
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000

# UI
cd frontend && cp .env.example .env.local   # optional
npm install && npm run dev
```

Open http://127.0.0.1:3000 with the API on 8000.

## Still out of scope after M8

- Discord alerts (M9).
- README polish / model card / Railway repair (M10).
- Flipping daily predict off `baseline-m3-v1`.
- Pre-tip schedule ingest.
