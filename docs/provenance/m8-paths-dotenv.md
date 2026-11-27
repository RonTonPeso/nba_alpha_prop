# M8 path resolution and dotenv load-once

Written on `feedback-fixes` after `docs/reviewer-m5-m7-m8.md` (Docker
`parents[3]` → `/`; `load_dotenv` at import resurrects keys).

## Acceptance aimed at

- Dashboard / lineup paths must resolve under Docker `WORKDIR /app`, not `/`.
- Unsetting `ANTHROPIC_API_KEY` in a process must not be undone by a second
  `load_dotenv` from `engine` import.

## Choice

- Added `app.paths.find_repo_root()` walking for monorepo markers
  (`docs/` + `backend/pyproject.toml` or `models/`) or image layout
  (`pyproject.toml` beside `app/`).
- Replaced brittle `parents[3]` / `parents[4]` call sites (engine, routes,
  lineup, fit, posterior_fit, backtest, injury run/eval).
- `load_repo_dotenv()` runs once with `override=False`; `NBA_LOAD_DOTENV=0`
  skips. Rejected keeping `parents[3]` plus a Docker-only env for artifact
  paths — easy to forget and already wrong in the image.

## What would make this wrong

- Image layout without `pyproject.toml` next to `app/` →
  `find_repo_root` raises; CI/unit test
  `test_find_repo_root_docker_layout` would need updating.
- `models/` still not copied into the image → lineup artifact missing at
  `/app/models/...` (path root fixed; artifact packaging is separate).

## Not verified

- Full Docker image build + `/api/calibration/summary` against a container
  was not run in this commit.
- Railway deploy still deferred.
