"""Targeted tests for the nba_api LeagueGameLog wrappers and parsers.

Coverage is intentionally selective: the round-trip test exercises the
full fetcher + cache path, and the bulk_load tests cover the parsers
end-to-end. Only parsers with non-trivial logic get unit tests here.
"""

from datetime import UTC, date, datetime
from typing import Any

from sqlmodel import Session

from app.data.cache import CachedHttpClient
from app.data.nba import (
    _event_time_from_game_date,
    _parse_minutes,
    fetch_league_game_log,
    player_game_log_row_to_orm,
    team_game_log_rows_to_orm,
)
from app.db.availability import reconstructed_available_at
from tests._fakes import FakeResponse, FakeSession


def test_parse_minutes_handles_various_formats() -> None:
    assert _parse_minutes("32:30") == 32.5
    assert _parse_minutes("32:00") == 32.0
    assert _parse_minutes(32.5) == 32.5
    assert _parse_minutes(32) == 32.0
    assert _parse_minutes(None) is None
    assert _parse_minutes("") is None
    assert _parse_minutes("garbage") is None
    assert _parse_minutes("1:2:3") is None


def test_event_time_is_next_day_midnight_utc() -> None:
    assert _event_time_from_game_date("2024-01-05") == datetime(2024, 1, 6, tzinfo=UTC)
    assert _event_time_from_game_date("2024-12-31") == datetime(2025, 1, 1, tzinfo=UTC)


def test_player_row_to_orm_handles_dnp_missing_stats() -> None:
    """DNP rows have null MIN and absent stat fields; parser fills 0/None."""
    row = {
        "PLAYER_ID": 1,
        "PLAYER_NAME": "Bench Warmer",
        "TEAM_ID": 1610612744,
        "GAME_ID": "0022400001",
        "GAME_DATE": "2024-12-15",
        "MIN": None,
        "PLUS_MINUS": None,
    }
    pgl = player_game_log_row_to_orm(row, season="2024-25", season_type="Regular Season")
    assert pgl.minutes is None
    assert pgl.plus_minus is None
    assert pgl.points == 0
    assert pgl.rebounds == 0
    assert pgl.available_at == reconstructed_available_at(date(2024, 12, 15))


def test_team_rows_to_game_and_result() -> None:
    """T-level pair → (Game, GameResult). Verifies MATCHUP-based home/away."""
    home_row = {
        "TEAM_ID": 1610612747,
        "GAME_ID": "0022400123",
        "GAME_DATE": "2024-12-15",
        "MATCHUP": "LAL vs. BOS",
        "PTS": 112,
    }
    away_row = {
        "TEAM_ID": 1610612738,
        "GAME_ID": "0022400123",
        "GAME_DATE": "2024-12-15",
        "MATCHUP": "BOS @ LAL",
        "PTS": 108,
    }
    game, result = team_game_log_rows_to_orm(
        home_row, away_row, season="2024-25", season_type="Regular Season"
    )
    assert game.game_id == "0022400123"
    assert game.home_team_id == 1610612747
    assert game.away_team_id == 1610612738
    assert game.event_time == datetime(2024, 12, 16, tzinfo=UTC)
    assert result.available_at == reconstructed_available_at(date(2024, 12, 15))
    assert result.home_score == 112
    assert result.away_score == 108
    assert result.status == "final"


def test_fetch_league_game_log_round_trip(db_session: Session) -> None:
    """End-to-end: synthetic JSON via FakeSession, parser yields rows,
    second call hits cache."""
    body = {
        "resultSets": [
            {
                "headers": ["PLAYER_ID", "PLAYER_NAME", "GAME_ID"],
                "rowSet": [[1, "Test Player", "0022400001"]],
            }
        ]
    }

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        assert "leaguegamelog" in url
        assert params["Season"] == "2024-25"
        assert params["PlayerOrTeam"] == "P"
        assert headers["x-nba-stats-token"] == "true"
        return FakeResponse(200, body)

    session = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=session)

    rows = fetch_league_game_log(cache, season="2024-25")
    assert rows == [{"PLAYER_ID": 1, "PLAYER_NAME": "Test Player", "GAME_ID": "0022400001"}]
    assert session.call_count == 1

    rows2 = fetch_league_game_log(cache, season="2024-25")
    assert rows2 == rows
    assert session.call_count == 1
