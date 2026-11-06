"""Pure tests for the M3 rolling-mean baseline.

No database. The point-in-time cases live in test_baseline_db.py, because
those have to prove the query filter, not just the arithmetic.
"""

from datetime import date, timedelta

from app.models.baseline import (
    HistoryGame,
    forecast_prop,
    mean_absolute_error,
    over_hit_rate,
)


def _game(
    *,
    day: int,
    points: float,
    is_home: bool,
    team_id: int = 1,
    rebounds: float = 5,
    assists: float = 4,
) -> HistoryGame:
    return HistoryGame(
        game_date=date(2025, 1, 1) + timedelta(days=day),
        is_home=is_home,
        team_id=team_id,
        points=points,
        rebounds=rebounds,
        assists=assists,
    )


def _alternating_dates(values: list[tuple[int, bool]]) -> list[HistoryGame]:
    """Newest first. Two days apart so every gap is rest, not a back-to-back."""
    games: list[HistoryGame] = []
    # day numbers decrease as we go older, so index 0 is the newest.
    start = 60
    for index, (points, is_home) in enumerate(values):
        games.append(_game(day=start - index * 2, points=float(points), is_home=is_home))
    return games


def test_abstains_below_five_games() -> None:
    history = _alternating_dates([(10, True)] * 4)
    assert forecast_prop(history, prop_type="points", is_home=True, rest_days=2) is None


def test_flat_window_uses_the_mean_and_a_std_floor() -> None:
    history = _alternating_dates([(10, True)] * 5)
    forecast = forecast_prop(history, prop_type="points", is_home=True, rest_days=2)
    assert forecast is not None
    assert forecast.mean == 10
    assert forecast.std == 0.5
    assert forecast.n_games == 5
    assert forecast.low_confidence is True
    assert forecast.quantile_50 == 10
    assert forecast.quantile_10 < forecast.mean < forecast.quantile_90


def test_home_adjustment_is_half_the_venue_gap() -> None:
    # 8 home games at 20, then 7 away games at 10. Newest first.
    history = _alternating_dates([(20, True)] * 8 + [(10, False)] * 7)
    home = forecast_prop(history, prop_type="points", is_home=True, rest_days=2)
    away = forecast_prop(history, prop_type="points", is_home=False, rest_days=2)
    assert home is not None and away is not None
    # Unadjusted mean is 230/15. Half of a +10 home gap is +5 at home and -5 away.
    assert abs(home.mu_window - (230 / 15)) < 1e-9
    assert home.home_effect == 10
    assert abs(home.mean - (230 / 15 + 5)) < 1e-9
    assert abs(away.mean - (230 / 15 - 5)) < 1e-9


def test_counting_stat_is_clipped_at_zero() -> None:
    history = _alternating_dates([(0, True)] * 8 + [(50, False)] * 7)
    forecast = forecast_prop(history, prop_type="points", is_home=True, rest_days=2)
    assert forecast is not None
    assert forecast.mean == 0.0


def test_window_ignores_games_older_than_fifteen_for_the_mean() -> None:
    recent = [(10, True)] * 15
    older = [(100, True)] * 5
    history = _alternating_dates(recent + older)
    forecast = forecast_prop(history, prop_type="points", is_home=True, rest_days=2)
    assert forecast is not None
    assert forecast.mu_window == 10
    assert forecast.n_games == 15
    assert forecast.low_confidence is False


def test_over_hit_rate_treats_the_line_as_greater_or_equal() -> None:
    # Predicted 20 vs line 20 is an over. Actual 20 is an over. That is a hit.
    result = over_hit_rate([(20, 20, 20), (20, 30, 25), (20, 18, 15)])
    assert result is not None
    hits, trials = result
    assert trials == 3
    assert hits == 2


def test_mae_is_the_mean_absolute_miss() -> None:
    assert mean_absolute_error([]) is None
    assert mean_absolute_error([(10, 12), (10, 8)]) == 2
    assert over_hit_rate([]) is None
