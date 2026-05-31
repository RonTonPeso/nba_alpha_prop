"""Tests for the nba_api LeagueGameLog wrappers and parsers."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlmodel import Session

from app.data.cache import CachedHttpClient
from app.data.nba import (
    _event_time_from_game_date,
    _parse_minutes,
    _parse_result_set,
    _split_home_away,
    fetch_league_game_log,
    player_game_log_row_to_orm,
    player_identity_from_row,
    team_game_log_rows_to_orm,
    team_identity_from_row,
)
from tests._fakes import FakeResponse, FakeSession


def test_parse_result_set_zips_headers_and_rows() -> None:
    body = {
        "resultSets": [
            {
                "headers": ["A", "B", "C"],
                "rowSet": [[1, 2, 3], [4, 5, 6]],
            }
        ]
    }
    assert _parse_result_set(body) == [
        {"A": 1, "B": 2, "C": 3},
        {"A": 4, "B": 5, "C": 6},
    ]


def test_parse_minutes_handles_various_formats() -> None:
    assert _parse_minutes("32:30") == 32.5
    assert _parse_minutes("32:00") == 32.0
    assert _parse_minutes(32.5) == 32.5
    assert _parse_minutes(32) == 32.0
    assert _parse_minutes(None) is None
    assert _parse_minutes("") is None
    assert _parse_minutes("garbage") is None
    assert _parse_minutes("1:2:3") is None  # bad shape


def test_event_time_is_next_day_midnight_utc() -> None:
    assert _event_time_from_game_date("2024-01-05") == datetime(2024, 1, 6, tzinfo=UTC)
    assert _event_time_from_game_date("2024-12-31") == datetime(2025, 1, 1, tzinfo=UTC)


def test_player_row_to_orm_maps_all_fields() -> None:
    row = {
        "PLAYER_ID": 201939,
        "PLAYER_NAME": "Stephen Curry",
        "TEAM_ID": 1610612744,
        "GAME_ID": "0022400123",
        "GAME_DATE": "2024-12-15",
        "MIN": "34:22",
        "PTS": 30,
        "REB": 5,
        "OREB": 1,
        "DREB": 4,
        "AST": 7,
        "STL": 2,
        "BLK": 0,
        "TOV": 3,
        "PF": 2,
        "FGM": 10,
        "FGA": 20,
        "FG3M": 5,
        "FG3A": 11,
        "FTM": 5,
        "FTA": 5,
        "PLUS_MINUS": 12,
    }
    pgl = player_game_log_row_to_orm(row, season="2024-25", season_type="Regular Season")
    assert pgl.player_id == 201939
    assert pgl.game_id == "0022400123"
    assert pgl.team_id == 1610612744
    assert pgl.season == "2024-25"
    assert pgl.season_type == "Regular Season"
    assert pgl.event_time == datetime(2024, 12, 16, tzinfo=UTC)
    assert pgl.minutes == pytest.approx(34 + 22 / 60)
    assert pgl.points == 30
    assert pgl.rebounds == 5
    assert pgl.offensive_rebounds == 1
    assert pgl.defensive_rebounds == 4
    assert pgl.assists == 7
    assert pgl.plus_minus == 12
    assert pgl.raw_data == row


def test_player_row_to_orm_handles_dnp_missing_stats() -> None:
    row = {
        "PLAYER_ID": 1,
        "PLAYER_NAME": "Bench Warmer",
        "TEAM_ID": 1610612744,
        "GAME_ID": "0022400001",
        "GAME_DATE": "2024-12-15",
        "MIN": None,
        "PLUS_MINUS": None,
        # other stat fields absent
    }
    pgl = player_game_log_row_to_orm(row, season="2024-25", season_type="Regular Season")
    assert pgl.minutes is None
    assert pgl.plus_minus is None
    assert pgl.points == 0
    assert pgl.rebounds == 0


def test_player_identity_extracts_id_and_name() -> None:
    row = {"PLAYER_ID": 201939, "PLAYER_NAME": "Stephen Curry"}
    p = player_identity_from_row(row)
    assert p.player_id == 201939
    assert p.current_name == "Stephen Curry"


def test_team_identity_from_t_level_row() -> None:
    row = {
        "TEAM_ID": 1610612747,
        "TEAM_CITY": "Los Angeles",
        "TEAM_NAME": "Lakers",
        "TEAM_ABBREVIATION": "LAL",
    }
    t = team_identity_from_row(row)
    assert t.team_id == 1610612747
    assert t.city == "Los Angeles"
    assert t.name == "Lakers"
    assert t.abbreviation == "LAL"


def test_split_home_away_uses_matchup_string() -> None:
    home = {"MATCHUP": "LAL vs. BOS"}
    away = {"MATCHUP": "BOS @ LAL"}
    assert _split_home_away(home, away) == (home, away)
    # Order should not matter.
    assert _split_home_away(away, home) == (home, away)


def test_split_home_away_raises_on_unrecognized_matchup() -> None:
    with pytest.raises(ValueError):
        _split_home_away({"MATCHUP": "weird"}, {"MATCHUP": "format"})


def test_team_rows_to_game_and_result() -> None:
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
    assert game.season == "2024-25"
    assert game.event_time == datetime(2024, 12, 16, tzinfo=UTC)
    assert game.scheduled_tip_time_utc is None
    assert result.home_score == 112
    assert result.away_score == 108
    assert result.status == "final"


def test_team_rows_raises_on_game_id_mismatch() -> None:
    row_a = {"GAME_ID": "0022400001", "MATCHUP": "LAL vs. BOS"}
    row_b = {"GAME_ID": "0022400002", "MATCHUP": "BOS @ LAL"}
    with pytest.raises(ValueError, match="share GAME_ID"):
        team_game_log_rows_to_orm(row_a, row_b, season="2024-25", season_type="Regular Season")


def test_fetch_league_game_log_round_trip(db_session: Session) -> None:
    """End-to-end: synthetic JSON via FakeSession, parser yields rows."""
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
