"""APScheduler setup for in-process scheduled jobs.

Currently registers one job: the daily NBA ingestion at 12:00 UTC.

The scheduler is started from FastAPI's lifespan handler in
``app/main.py``, gated on the ``SCHEDULER_ENABLED`` env var so tests
and local dev don't auto-fire jobs. Set ``SCHEDULER_ENABLED=true`` in
the production env (Railway).
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.data.daily import run_daily_ingest

logger = logging.getLogger(__name__)


def make_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_daily_ingest,
        CronTrigger(hour=12, minute=0, timezone="UTC"),
        id="daily_ingest",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler configured with daily_ingest at 12:00 UTC")
    return scheduler
