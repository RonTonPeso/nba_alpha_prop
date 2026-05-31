"""Daily NBA ingestion job.

Runs once per day, fetches yesterday's games via ``LeagueGameLog`` with
``DateFrom``/``DateTo`` set, and upserts via the same ``load_season``
code path as the bulk loader. Idempotent.

Scheduled by ``app/scheduler.py`` at 12:00 UTC = 8 AM ET, well after
all NBA games (incl. West Coast late starts) have ended for the prior
ET day. ``GAME_DATE`` from ``LeagueGameLog`` follows Eastern Time
convention; running well after midnight ET ensures we don't miss late
Pacific-Time games that ended on the next UTC day.

For MVP, only Regular Season is ingested by the daily job. Playoffs
require running this with ``season_type="Playoffs"`` and that's a
manual call for now.
"""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlmodel import Session

from app.data.bulk_load import SeasonLoadSummary, load_season
from app.data.cache import CachedHttpClient
from app.db.engine import get_engine

logger = logging.getLogger(__name__)


def current_season(today: date) -> str:
    """Map a calendar date to its NBA season string.

    Cutoff is July 1. July onward → season starting that year (e.g.,
    July 2024 → "2024-25"). January-June → season that started the
    prior year (e.g., March 2025 → "2024-25").
    """
    if today.month >= 7:
        start_year = today.year
    else:
        start_year = today.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def run_daily_ingest(today: date | None = None) -> SeasonLoadSummary:
    """Ingest yesterday's games. Opens its own session and commits.

    ``today`` is overridable for testing; defaults to the UTC date now.
    """
    today = today or datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    season = current_season(today)

    logger.info("Daily ingest: today=%s yesterday=%s season=%s", today, yesterday, season)

    engine = get_engine()
    with Session(engine) as session, CachedHttpClient(session) as client:
        summary = load_season(
            client,
            session,
            season=season,
            season_type="Regular Season",
            date_from=yesterday,
            date_to=yesterday,
        )
        session.commit()
    return summary
