"""Database query helpers.
Enforces important invariant -
 A query at simulated time ``as_of`` may only see rows where
``event_time < as_of AND ingested_at <= as_of``.
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

    Filters on both ``event_time < as_of`` (the basketball fact happened
    before ``as_of``) and ``ingested_at <= as_of`` (the system recorded
    the fact by ``as_of``). Most recent first. Pass ``limit`` to bound
    the rolling window.
    """
    statement = (
        select(PlayerGameLog)
        .where(PlayerGameLog.player_id == player_id)
        .where(PlayerGameLog.event_time < as_of)
        .where(PlayerGameLog.ingested_at <= as_of)
        # mypy sees event_time as `datetime` (Pydantic) rather than as a SQLAlchemy
        # col, the runtime descriptor is fine. SQLModel and strict mypy quirk.
        .order_by(desc(PlayerGameLog.event_time))  # type: ignore[arg-type]
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement).all())
