"""Database query helpers.

A feature query at simulated time ``as_of`` may only see box scores
where ``event_time < as_of`` and ``available_at <= as_of``.
``ingested_at`` is the fetch time and is not this filter.
"""

from datetime import datetime

from sqlalchemy import desc  # to make mypy happy
from sqlmodel import Session, select

from app.db.tables import PlayerGameLog


def query_player_game_logs(
    *,
    player_id: int,
    as_of: datetime,
    session: Session,
    limit: int | None = None,
) -> list[PlayerGameLog]:
    """Return player_game_logs for ``player_id`` known at simulated ``as_of``.

    Filters on ``event_time < as_of`` and ``available_at <= as_of``.
    A bulk row can have a 2026 ``ingested_at`` and still be visible, if
    its ``available_at`` is the morning after the game. Most recent
    first. Pass ``limit`` to bound the rolling window.
    """
    statement = (
        select(PlayerGameLog)
        .where(PlayerGameLog.player_id == player_id)
        .where(PlayerGameLog.event_time < as_of)
        .where(PlayerGameLog.available_at <= as_of)
        # mypy sees event_time as `datetime` (Pydantic) rather than as a SQLAlchemy
        # col, the runtime descriptor is fine. SQLModel and strict mypy quirk.
        .order_by(desc(PlayerGameLog.event_time))  # type: ignore[arg-type]
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement).all())
