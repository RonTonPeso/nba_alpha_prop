# CI Postgres so DB tests actually run

Written on the `feedback-fixes` branch after
`docs/reviewer-m5-m7-m8.md` (cross-cut: CI never runs Postgres tests).

## Acceptance aimed at

Reviewer order item 3 / cross-cut: point-in-time and other DB-backed
tests must execute in CI, not skip silently when `db_engine` cannot
connect.

Roadmap / process expectation: green CI means the suite ran, including
fixtures that need Postgres (`backend/tests/conftest.py`).

## Choice

Add a `postgres:16` service to `.github/workflows/ci.yml`, set
`DATABASE_URL=postgresql+psycopg://nba:nba@localhost:5432/nba_alpha_prop`,
wait via healthcheck, run `alembic upgrade head`, then `pytest -q`.

**Rejected:** Keep skip-on-connect and document “run DB tests locally.”
That left CI green while every `db_session` test was skipped — exactly
what the review called silent green.

## What would make this wrong

- Workflow URL / credentials disagree with what `get_engine` expects →
  migrate or pytest fail loudly (good) or still skip (bad; watch for
  “Postgres unavailable” in CI logs).
- Migrations fail on empty DB → CI red until alembic is fixed.
- A test mutates outside the rollback fixture → flakes or polluted
  service DB within the job only.

## Not verified

- This commit has not been observed on GitHub Actions yet (no push of
  `feedback-fixes` required for the YAML change itself).
- Local `act` was not run.
