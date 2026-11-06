"""Sanity test: the scheduler jobs are registered."""

from app.scheduler import make_scheduler


def test_scheduler_registers_jobs() -> None:
    scheduler = make_scheduler()
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert job_ids == {"daily_ingest", "daily_predict", "kalshi_snapshot"}
