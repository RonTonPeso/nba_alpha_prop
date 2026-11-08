"""When a bulk-loaded box score counts as known.

``ingested_at`` is the fetch time. For rows loaded months after the
game, that clock hides every prior season. ``available_at`` is the
stand-in: 12:00 UTC on the calendar day after ``game_date``, which is
when the daily job is scheduled to have run. A live fetch sets
``available_at`` to the same instant as ``ingested_at``, so a late job
does not claim noon.

Feature reads use ``event_time < as_of`` and ``available_at <= as_of``.
Market quotes stay on ``quoted_at`` and ``ingested_at``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


def reconstructed_available_at(game_date: date) -> datetime:
    """12:00 UTC on the day after ``game_date``."""
    day = game_date + timedelta(days=1)
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
