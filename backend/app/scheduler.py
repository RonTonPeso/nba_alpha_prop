"""APScheduler setup for in-process scheduled jobs.

Registers two jobs:

- ``daily_ingest`` at 12:00 UTC: pulls yesterday's NBA box scores.
- ``kalshi_snapshot`` every 5 minutes: snapshots active Kalshi NBA
  prop markets and opportunistically writes settlements for any market
  that finalized since last tick.

The scheduler is started from FastAPI's lifespan handler in
``app/main.py``, gated on the ``SCHEDULER_ENABLED`` env var so tests
and local dev don't auto-fire jobs. Set ``SCHEDULER_ENABLED=true`` in
the production env (Railway).
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.data.daily import run_daily_ingest
from app.data.kalshi_snapshot import run_snapshot

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
    scheduler.add_job(
        run_snapshot,
        IntervalTrigger(minutes=5),
        id="kalshi_snapshot",
        replace_existing=True,
        misfire_grace_time=60,
    )
    logger.info("Scheduler configured: daily_ingest at 12:00 UTC, kalshi_snapshot every 5 min")
    return scheduler
