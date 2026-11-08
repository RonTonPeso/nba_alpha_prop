"""Feature clock and the ten-column vector. No database."""

from datetime import UTC, date, datetime

from app.models.features import (
    FEATURE_NAMES,
    PlayerLog,
    TeamPointsAllowed,
    build_feature_row,
    opponent_points_allowed,
    visible_logs,
)


def _log(
    day: int,
    *,
    points: float = 10,
    rebounds: float = 4,
    assists: float = 3,
    minutes: float | None = 30,
    fga: float = 10,
    fta: float = 0,
    tov: float = 0,
    team_id: int = 1,
    available_day: int | None = None,
    event_hour: int = 22,
) -> PlayerLog:
    available = day + 1 if available_day is None else available_day
    return PlayerLog(
        game_id=f"g{day}-{event_hour}",
        game_date=date(2025, 1, day),
        team_id=team_id,
        is_home=True,
        event_time=datetime(2025, 1, day, event_hour, tzinfo=UTC),
        available_at=datetime(2025, 1, available, 12, tzinfo=UTC),
        points=points,
        rebounds=rebounds,
        assists=assists,
        minutes=minutes,
        fga=fga,
        fta=fta,
        tov=tov,
    )


def _as_of(day: int) -> datetime:
    return datetime(2025, 1, day, 16, tzinfo=UTC)


def test_visible_logs_drop_a_future_available_at() -> None:
    as_of = _as_of(10)
    kept = _log(8)
    hidden = _log(9, available_day=11)
    visible = visible_logs([hidden, kept], as_of)
    assert [log.game_id for log in visible] == [kept.game_id]


def test_visible_logs_keep_a_late_fetch_once_available_at_has_passed() -> None:
    """ingested_at is not on the log. The morning-after clock is what counts."""
    as_of = _as_of(10)
    row = _log(8)
    assert row.available_at <= as_of
    assert visible_logs([row], as_of) == [row]


def test_visible_logs_drop_an_event_after_the_clock() -> None:
    as_of = _as_of(10)
    later = _log(10, event_hour=20)
    assert visible_logs([later], as_of) == []


def test_means_rest_cap_and_days_since_30() -> None:
    prior = [
        _log(1, points=0),
        _log(2, points=0),
        _log(3, points=0),
        _log(4, points=0),
        _log(5, points=30),
        _log(6, points=10),
        _log(7, points=10),
        _log(8, points=10),
        _log(9, points=10),
        _log(10, points=10),
    ]
    row = build_feature_row(
        prior,
        game_date=date(2025, 1, 28),
        home_team_id=1,
        away_team_id=2,
        as_of=_as_of(28),
        team_usage={},
        team_games={},
    )
    assert row is not None
    by_name = dict(zip(FEATURE_NAMES, row.values, strict=True))
    assert by_name["pts_mean_5"] == 10
    assert by_name["pts_mean_15"] == 8
    assert by_name["reb_mean_15"] == 4
    assert by_name["ast_mean_15"] == 3
    assert by_name["min_mean_15"] == 30
    assert by_name["is_home"] == 1
    assert row.rest_days == 18
    assert by_name["rest_capped"] == 14
    assert by_name["days_since_30_capped"] == 23


def test_days_since_30_caps_at_60_when_the_game_is_older() -> None:
    prior = [_log(day, points=30 if day == 1 else 10) for day in range(1, 6)]
    row = build_feature_row(
        prior,
        game_date=date(2025, 3, 15),
        home_team_id=1,
        away_team_id=2,
        as_of=datetime(2025, 3, 15, 16, tzinfo=UTC),
        team_usage={(log.game_id, log.team_id): 40 for log in prior},
        team_games={},
    )
    assert row is not None
    assert dict(zip(FEATURE_NAMES, row.values, strict=True))["days_since_30_capped"] == 60


def test_usage_share_includes_the_player_in_the_team_sum() -> None:
    prior = [_log(day, fga=10) for day in range(1, 6)]
    team_usage = {(log.game_id, log.team_id): 40.0 for log in prior}
    row = build_feature_row(
        prior,
        game_date=date(2025, 1, 10),
        home_team_id=1,
        away_team_id=2,
        as_of=_as_of(10),
        team_usage=team_usage,
        team_games={},
    )
    assert row is not None
    assert dict(zip(FEATURE_NAMES, row.values, strict=True))["usage_share"] == 0.25


def test_opponent_points_ignore_a_later_available_at() -> None:
    as_of = _as_of(10)
    games = [
        TeamPointsAllowed(
            event_time=datetime(2025, 1, 8, 22, tzinfo=UTC),
            available_at=datetime(2025, 1, 9, 12, tzinfo=UTC),
            points_allowed=100,
        ),
        TeamPointsAllowed(
            event_time=datetime(2025, 1, 9, 22, tzinfo=UTC),
            available_at=datetime(2025, 1, 12, 12, tzinfo=UTC),
            points_allowed=140,
        ),
    ]
    assert opponent_points_allowed(games, as_of) == 100
    prior = [_log(day) for day in range(1, 6)]
    row = build_feature_row(
        prior,
        game_date=date(2025, 1, 10),
        home_team_id=1,
        away_team_id=2,
        as_of=as_of,
        team_usage={(log.game_id, log.team_id): 40.0 for log in prior},
        team_games={2: games},
    )
    assert row is not None
    assert dict(zip(FEATURE_NAMES, row.values, strict=True))["opp_pts_allowed_15"] == 100


def test_short_history_and_a_traded_team_abstain() -> None:
    short = [_log(day) for day in range(1, 5)]
    assert (
        build_feature_row(
            short,
            game_date=date(2025, 1, 10),
            home_team_id=1,
            away_team_id=2,
            as_of=_as_of(10),
            team_usage={},
            team_games={},
        )
        is None
    )
    traded = [_log(day, team_id=9) for day in range(1, 6)]
    assert (
        build_feature_row(
            traded,
            game_date=date(2025, 1, 10),
            home_team_id=1,
            away_team_id=2,
            as_of=_as_of(10),
            team_usage={},
            team_games={},
        )
        is None
    )
