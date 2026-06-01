"""Sanity test: both scheduler jobs are registered."""

from app.scheduler import make_scheduler


def test_scheduler_registers_both_jobs() -> None:
    scheduler = make_scheduler()
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert job_ids == {"daily_ingest", "kalshi_snapshot"}
