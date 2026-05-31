"""Tests for the spot-check helper."""

from datetime import UTC, date, datetime

from sqlmodel import Session

from app.data.spot_check import _format_minutes, format_game, pick_random_game_ids
from app.db.tables import Game, GameResult, Player, PlayerGameLog, Team


def test_format_minutes_handles_fractional_and_none() -> None:
    assert _format_minutes(34.5) == "34:30"
    assert _format_minutes(34.0) == "34:00"
    assert _format_minutes(None) == "DNP"


def _seed_one_game(session: Session) -> str:
    game_id = "0099900123"
    session.add(Team(team_id=997_001, name="Testers", city="Test City", abbreviation="TST"))
    session.add(Team(team_id=997_002, name="Foes", city="Foe Town", abbreviation="FOE"))
    session.add(Player(player_id=997_010, current_name="Alpha Player"))
    session.add(Player(player_id=997_020, current_name="Beta Player"))
    session.flush()

    event_time = datetime(2024, 12, 16, tzinfo=UTC)
    session.add(
        Game(
            game_id=game_id,
            season="2024-25",
            season_type="Regular Season",
            game_date=date(2024, 12, 15),
            home_team_id=997_001,
            away_team_id=997_002,
            event_time=event_time,
        )
    )
    session.flush()
    session.add(
        GameResult(
            game_id=game_id,
            home_score=110,
            away_score=108,
            status="final",
            event_time=event_time,
        )
    )
    session.add(
        PlayerGameLog(
            player_id=997_010,
            game_id=game_id,
            team_id=997_001,
            season="2024-25",
            season_type="Regular Season",
            event_time=event_time,
            minutes=34.5,
            points=28,
            rebounds=9,
            assists=7,
        )
    )
    session.add(
        PlayerGameLog(
            player_id=997_020,
            game_id=game_id,
            team_id=997_002,
            season="2024-25",
            season_type="Regular Season",
            event_time=event_time,
            minutes=32.0,
            points=22,
            rebounds=5,
            assists=4,
        )
    )
    session.flush()
    return game_id


def test_format_game_produces_readable_box_score(db_session: Session) -> None:
    game_id = _seed_one_game(db_session)
    out = format_game(db_session, game_id)

    # Header line: date, away @ home, score
    assert "2024-12-15" in out
    assert "FOE @ TST" in out
    assert "108-110" in out

    # Both team blocks and both players present
    assert "Foe Town Foes (away)" in out
    assert "Test City Testers (home)" in out
    assert "Alpha Player" in out
    assert "Beta Player" in out

    # Stats appear
    assert "28 pts" in out
    assert "22 pts" in out


def test_format_game_missing_game_id_returns_message(db_session: Session) -> None:
    out = format_game(db_session, "0000000000")
    assert "not found" in out


def test_pick_random_game_ids_is_deterministic_with_seed(db_session: Session) -> None:
    # Seed two games so sampling has options.
    _seed_one_game(db_session)
    session = db_session
    # Add a second game
    session.add(
        Game(
            game_id="0099900124",
            season="2024-25",
            season_type="Regular Season",
            game_date=date(2024, 12, 16),
            home_team_id=997_001,
            away_team_id=997_002,
            event_time=datetime(2024, 12, 17, tzinfo=UTC),
        )
    )
    session.flush()

    a = pick_random_game_ids(db_session, 2, seed=42)
    b = pick_random_game_ids(db_session, 2, seed=42)
    assert a == b
    assert len(a) == 2


def test_pick_random_game_ids_returns_empty_on_empty_db(db_session: Session) -> None:
    assert pick_random_game_ids(db_session, 3) == []
