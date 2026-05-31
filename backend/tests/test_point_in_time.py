"""Regression test for point-in-time correctness on player_game_logs.

This is the single most important test in the project. It proves the
schema's ``event_time`` / ``ingested_at`` filter actually prevents
future data from leaking into historical queries.

Five cases:
1. A row visible at simulated ``as_of`` comes back.
2. A row with ``event_time`` in the future is excluded.
3. A row with past ``event_time`` but future ``ingested_at`` is
   excluded. The sneaky case: the game happened but we didn't know
   about it yet.
4. Rows for other players are excluded.
5. Calling the helper without an explicit ``as_of`` raises TypeError.
"""

from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from app.db.queries import query_player_game_logs
from app.db.tables import Game, Player, PlayerGameLog, Team

# Use high IDs to avoid collisions with other possible stuff in the dev db
TEST_PLAYER_ID = 999_001
OTHER_PLAYER_ID = 999_002
TEST_TEAM_ID = 999_001
TEST_GAME_ID = "999_test_game"


def _seed_identity(session: Session) -> None:
    """Insert one Player, one Team, one Game for FK constraints.

    Flushes Team before Game because SQLModel's foreign_key declarations
    don't always feed SQLAlchemy's topo sort, so we
    can't rely on automatic ordering inside one flush.

    """
    session.add(Player(player_id=TEST_PLAYER_ID, current_name="Test Player"))
    session.add(
        Team(
            team_id=TEST_TEAM_ID,
            name="Testers",
            city="Test City",
            abbreviation="TST",
        )
    )
    session.flush()
    session.add(
        Game(
            game_id=TEST_GAME_ID,
            season="2024-25",
            season_type="Regular Season",
            game_date=datetime(2024, 1, 1).date(),
            home_team_id=TEST_TEAM_ID,
            away_team_id=TEST_TEAM_ID,
            event_time=datetime(2024, 1, 1, 19, 0, tzinfo=UTC),
        )
    )
    session.flush()


# builds a PlayerGameLog with defaults
def _make_pgl(
    *,
    event_time: datetime,
    ingested_at: datetime,
    points: int,
    player_id: int = TEST_PLAYER_ID,
) -> PlayerGameLog:
    return PlayerGameLog(
        player_id=player_id,
        game_id=TEST_GAME_ID,
        team_id=TEST_TEAM_ID,
        season="2024-25",
        season_type="Regular Season",
        event_time=event_time,
        ingested_at=ingested_at,
        points=points,
    )


def test_visible_row_is_returned(db_session: Session) -> None:
    _seed_identity(db_session)
    db_session.add(
        _make_pgl(
            event_time=datetime(2024, 1, 1, 22, 0, tzinfo=UTC),
            ingested_at=datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
            points=20,
        )
    )
    db_session.flush()

    rows = query_player_game_logs(
        player_id=TEST_PLAYER_ID,
        as_of=datetime(2024, 1, 10, 12, 0, tzinfo=UTC),
        session=db_session,
    )

    assert len(rows) == 1
    assert rows[0].points == 20


def test_future_event_time_is_excluded(db_session: Session) -> None:
    _seed_identity(db_session)
    db_session.add(
        _make_pgl(
            event_time=datetime(2024, 1, 15, 22, 0, tzinfo=UTC),  # after as_of
            ingested_at=datetime(2024, 1, 16, 8, 0, tzinfo=UTC),
            points=30,
        )
    )
    db_session.flush()

    rows = query_player_game_logs(
        player_id=TEST_PLAYER_ID,
        as_of=datetime(2024, 1, 10, 12, 0, tzinfo=UTC),
        session=db_session,
    )

    assert rows == []


def test_future_ingested_at_is_excluded(db_session: Session) -> None:
    """The subtle case: game happened, but the system hadn't ingested it yet."""
    _seed_identity(db_session)
    db_session.add(
        _make_pgl(
            event_time=datetime(2024, 1, 5, 22, 0, tzinfo=UTC),  # game happened
            ingested_at=datetime(2024, 1, 20, 8, 0, tzinfo=UTC),  # but ingested later
            points=42,
        )
    )
    db_session.flush()

    rows = query_player_game_logs(
        player_id=TEST_PLAYER_ID,
        as_of=datetime(2024, 1, 10, 12, 0, tzinfo=UTC),
        session=db_session,
    )

    assert rows == []


def test_rolling_average_does_not_leak_future_data(db_session: Session) -> None:
    """The example from notebook_notes.md: correct avg = 20.0, leaked = 25.0."""
    _seed_identity(db_session)
    db_session.add(
        _make_pgl(
            event_time=datetime(2024, 1, 1, 22, 0, tzinfo=UTC),
            ingested_at=datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
            points=20,
        )
    )
    db_session.add(
        _make_pgl(
            event_time=datetime(2024, 1, 15, 22, 0, tzinfo=UTC),
            ingested_at=datetime(2024, 1, 16, 8, 0, tzinfo=UTC),
            points=30,
        )
    )
    db_session.flush()

    rows = query_player_game_logs(
        player_id=TEST_PLAYER_ID,
        as_of=datetime(2024, 1, 10, 12, 0, tzinfo=UTC),
        session=db_session,
    )
    avg = sum(r.points for r in rows) / len(rows)

    assert avg == 20.0  # Correct. 25.0 would be a leak from the future row.


def test_other_players_are_excluded(db_session: Session) -> None:
    _seed_identity(db_session)
    db_session.add(Player(player_id=OTHER_PLAYER_ID, current_name="Other Player"))
    db_session.flush()

    visible_time = datetime(2024, 1, 1, 22, 0, tzinfo=UTC)
    db_session.add(
        _make_pgl(
            event_time=visible_time,
            ingested_at=datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
            points=20,
        )
    )
    db_session.add(
        _make_pgl(
            event_time=visible_time,
            ingested_at=datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
            points=100,
            player_id=OTHER_PLAYER_ID,
        )
    )
    db_session.flush()

    rows = query_player_game_logs(
        player_id=TEST_PLAYER_ID,
        as_of=datetime(2024, 2, 1, tzinfo=UTC),
        session=db_session,
    )

    assert len(rows) == 1
    assert rows[0].points == 20  # Not 100.


def test_as_of_is_keyword_only(db_session: Session) -> None:
    """The ``*,`` in the signature forces callers to think about time."""
    with pytest.raises(TypeError):
        query_player_game_logs(  # type: ignore[misc]
            TEST_PLAYER_ID,
            datetime.now(UTC),
            db_session,
        )
