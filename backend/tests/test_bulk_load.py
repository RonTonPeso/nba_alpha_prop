"""Tests for the bulk_load CLI orchestration.

Three behaviors verified:
1. ``iter_seasons`` produces the right sequence (incl. edge cases).
2. ``load_season`` round trip: synthetic LeagueGameLog responses end up
   as the expected rows in the DB.
3. Idempotency: a second ``load_season`` with the same data skips
   everything and makes zero new network calls.
"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlmodel import Session, select

from app.data.bulk_load import iter_seasons, load_season
from app.data.cache import CachedHttpClient
from app.db.tables import Game, GameResult, PlayerGameLog, Team
from tests._fakes import FakeResponse, FakeSession

# ----- iter_seasons -----


def test_iter_seasons_range() -> None:
    assert list(iter_seasons("2022-23", "2024-25")) == [
        "2022-23",
        "2023-24",
        "2024-25",
    ]


def test_iter_seasons_end_before_start_raises() -> None:
    with pytest.raises(ValueError):
        list(iter_seasons("2024-25", "2022-23"))


# ----- load_season -----


def _synthetic_responses() -> tuple[dict[str, Any], dict[str, Any]]:
    """Two games, three teams, three players. Just enough to exercise the loader."""
    t_body = {
        "resultSets": [
            {
                "headers": [
                    "TEAM_ID",
                    "TEAM_NAME",
                    "TEAM_CITY",
                    "TEAM_ABBREVIATION",
                    "GAME_ID",
                    "GAME_DATE",
                    "MATCHUP",
                    "PTS",
                ],
                "rowSet": [
                    [
                        1610612747,
                        "Lakers",
                        "Los Angeles",
                        "LAL",
                        "0022400001",
                        "2024-10-22",
                        "LAL vs. BOS",
                        110,
                    ],
                    [
                        1610612738,
                        "Celtics",
                        "Boston",
                        "BOS",
                        "0022400001",
                        "2024-10-22",
                        "BOS @ LAL",
                        105,
                    ],
                    [
                        1610612747,
                        "Lakers",
                        "Los Angeles",
                        "LAL",
                        "0022400002",
                        "2024-10-24",
                        "LAL @ GSW",
                        102,
                    ],
                    [
                        1610612744,
                        "Warriors",
                        "Golden State",
                        "GSW",
                        "0022400002",
                        "2024-10-24",
                        "GSW vs. LAL",
                        108,
                    ],
                ],
            }
        ]
    }
    p_body = {
        "resultSets": [
            {
                "headers": [
                    "PLAYER_ID",
                    "PLAYER_NAME",
                    "TEAM_ID",
                    "GAME_ID",
                    "GAME_DATE",
                    "MIN",
                    "PTS",
                    "REB",
                    "AST",
                    "OREB",
                    "DREB",
                    "STL",
                    "BLK",
                    "TOV",
                    "PF",
                    "FGM",
                    "FGA",
                    "FG3M",
                    "FG3A",
                    "FTM",
                    "FTA",
                    "PLUS_MINUS",
                ],
                "rowSet": [
                    [
                        2544,
                        "LeBron James",
                        1610612747,
                        "0022400001",
                        "2024-10-22",
                        "36:00",
                        30,
                        8,
                        7,
                        1,
                        7,
                        2,
                        1,
                        3,
                        2,
                        11,
                        20,
                        3,
                        7,
                        5,
                        5,
                        5,
                    ],
                    [
                        1628369,
                        "Jayson Tatum",
                        1610612738,
                        "0022400001",
                        "2024-10-22",
                        "38:00",
                        28,
                        6,
                        4,
                        0,
                        6,
                        1,
                        0,
                        2,
                        3,
                        10,
                        22,
                        4,
                        10,
                        4,
                        4,
                        -5,
                    ],
                    [
                        2544,
                        "LeBron James",
                        1610612747,
                        "0022400002",
                        "2024-10-24",
                        "34:00",
                        25,
                        7,
                        9,
                        1,
                        6,
                        1,
                        0,
                        2,
                        1,
                        9,
                        18,
                        2,
                        5,
                        5,
                        6,
                        -6,
                    ],
                    [
                        201939,
                        "Stephen Curry",
                        1610612744,
                        "0022400002",
                        "2024-10-24",
                        "35:00",
                        32,
                        4,
                        5,
                        0,
                        4,
                        2,
                        0,
                        3,
                        2,
                        11,
                        22,
                        6,
                        12,
                        4,
                        4,
                        6,
                    ],
                ],
            }
        ]
    }
    return t_body, p_body


def _handler(
    t_body: dict[str, Any], p_body: dict[str, Any]
) -> Callable[[str, dict[str, Any], dict[str, str]], FakeResponse]:
    def inner(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        pot = params.get("PlayerOrTeam")
        if pot == "T":
            return FakeResponse(200, t_body)
        if pot == "P":
            return FakeResponse(200, p_body)
        return FakeResponse(400, {"error": f"unexpected PlayerOrTeam={pot!r}"})

    return inner


def test_load_season_round_trip(db_session: Session) -> None:
    t_body, p_body = _synthetic_responses()
    session = FakeSession(_handler(t_body, p_body))
    cache = CachedHttpClient(db_session, client=session)

    summary = load_season(cache, db_session, season="2024-25", season_type="Regular Season")

    # Summary
    assert summary.t_rows == 4
    assert summary.p_rows == 4
    assert summary.teams_total == 3
    assert summary.teams_new == 3
    assert summary.players_total == 3
    assert summary.players_new == 3
    assert summary.games_inserted == 2
    assert summary.results_inserted == 2
    assert summary.pgls_inserted == 4
    assert session.call_count == 2  # one T call, one P call

    # DB state
    teams = list(db_session.exec(select(Team)).all())
    assert {t.abbreviation for t in teams} == {"LAL", "BOS", "GSW"}

    game1 = db_session.get(Game, "0022400001")
    assert game1 is not None
    assert game1.home_team_id == 1610612747  # LAL was home
    assert game1.away_team_id == 1610612738  # BOS was away

    results = list(db_session.exec(select(GameResult)).all())
    assert len(results) == 2
    r1 = next(r for r in results if r.game_id == "0022400001")
    assert r1.home_score == 110
    assert r1.away_score == 105

    pgls = list(db_session.exec(select(PlayerGameLog)).all())
    assert len(pgls) == 4
    lebron_rows = [p for p in pgls if p.player_id == 2544]
    assert len(lebron_rows) == 2  # LeBron played both games in the synthetic set


def test_load_season_is_idempotent(db_session: Session) -> None:
    t_body, p_body = _synthetic_responses()
    session = FakeSession(_handler(t_body, p_body))
    cache = CachedHttpClient(db_session, client=session)

    # First run
    load_season(cache, db_session, season="2024-25", season_type="Regular Season")
    assert session.call_count == 2

    # Second run with the same handler. Should be a no-op for inserts AND network.
    summary2 = load_season(cache, db_session, season="2024-25", season_type="Regular Season")

    assert summary2.teams_new == 0
    assert summary2.players_new == 0
    assert summary2.games_inserted == 0
    assert summary2.games_skipped == 2
    assert summary2.results_inserted == 0
    assert summary2.results_skipped == 2
    assert summary2.pgls_inserted == 0
    assert summary2.pgls_skipped == 4

    # Cache served both fetches; no second pair of network calls.
    assert session.call_count == 2

    # DB row counts unchanged.
    assert len(list(db_session.exec(select(Game)).all())) == 2
    assert len(list(db_session.exec(select(GameResult)).all())) == 2
    assert len(list(db_session.exec(select(PlayerGameLog)).all())) == 4
