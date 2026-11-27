"""APScheduler setup for in-process scheduled jobs.

Registers five jobs:

- ``daily_ingest`` at 12:00 UTC: pulls yesterday's NBA box scores.
- ``daily_predict`` at 16:00 UTC: baseline forecasts for today's Kalshi props.
- ``kalshi_snapshot`` every 5 minutes: snapshots active Kalshi NBA
  prop markets and opportunistically writes settlements for any market
  that finalized since last tick.
- ``injury_official`` hourly: official NBA injury report → classify → store.
- ``injury_rss`` every 15 minutes: ESPN / Bleacher Report RSS → classify → store.

Jobs are registered even when disabled. The scheduler is started from
FastAPI's lifespan handler in ``app/main.py``, gated on the
``SCHEDULER_ENABLED`` env var so tests and local dev don't auto-fire.
Set ``SCHEDULER_ENABLED=true`` in the production env (Railway).
M7 acceptance is a timed CLI, not a live tick.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session

from app.data.daily import run_daily_ingest
from app.data.injury.pipeline import run_injury_pipeline
from app.data.kalshi_snapshot import run_snapshot
from app.db.engine import get_engine
from app.models.predict import run_daily_predictions

logger = logging.getLogger(__name__)


def run_injury_official_job() -> None:
    with Session(get_engine()) as session:
        summary = run_injury_pipeline(
            session,
            include_official=True,
            include_rss=False,
            max_classify=80,
        )
    logger.info(
        "injury_official inserted=%d classified=%d scraped=%d",
        summary.inserted,
        summary.classified,
        summary.scraped,
    )


def run_injury_rss_job() -> None:
    with Session(get_engine()) as session:
        summary = run_injury_pipeline(
            session,
            include_official=False,
            include_rss=True,
            rss_limit=20,
            max_classify=40,
        )
    logger.info(
        "injury_rss inserted=%d classified=%d scraped=%d",
        summary.inserted,
        summary.classified,
        summary.scraped,
    )


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
        run_daily_predictions,
        CronTrigger(hour=16, minute=0, timezone="UTC"),
        id="daily_predict",
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
    scheduler.add_job(
        run_injury_official_job,
        CronTrigger(minute=5, timezone="UTC"),
        id="injury_official",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_injury_rss_job,
        IntervalTrigger(minutes=15),
        id="injury_rss",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info(
        "Scheduler configured: daily_ingest 12:00 UTC, daily_predict 16:00 UTC, "
        "kalshi_snapshot every 5 min, injury_official hourly, injury_rss every 15 min"
    )
    return scheduler
