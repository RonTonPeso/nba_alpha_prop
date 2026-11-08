"""Ten box-score features for the M5 point predictor.

Every input is a prior game that has already cleared the feature clock:
``event_time`` before the prediction time and ``available_at`` at or
before it. The target game is a label. It is not a feature.

Home or away comes from the most recent visible game's team. The
schema has no pre-tip roster. If that team is not in tonight's game,
there is no row.

``usage_share`` is the player's field-goal attempts, weighted free-throw
attempts, and turnovers, divided by the same sum for the whole team in
those games, including the player. It is a box-score share, not a
play-by-play usage rate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from app.models.baseline import MIN_GAMES, WINDOW

REST_CAP = 14
DAYS_SINCE_30_CAP = 60
POINTS_MARK = 30
FTA_WEIGHT = 0.44

FEATURE_NAMES: tuple[str, ...] = (
    "pts_mean_5",
    "pts_mean_15",
    "reb_mean_15",
    "ast_mean_15",
    "min_mean_15",
    "is_home",
    "rest_capped",
    "usage_share",
    "opp_pts_allowed_15",
    "days_since_30_capped",
)


@dataclass(frozen=True)
class PlayerLog:
    """One player-game the feature clock has already accepted, or a candidate."""

    game_id: str
    game_date: date
    team_id: int
    is_home: bool
    event_time: datetime
    available_at: datetime
    points: float
    rebounds: float
    assists: float
    minutes: float | None
    fga: float
    fta: float
    tov: float


@dataclass(frozen=True)
class TeamPointsAllowed:
    """Points the team gave up in one game. Oldest-first when stored."""

    event_time: datetime
    available_at: datetime
    points_allowed: float


@dataclass(frozen=True)
class FeatureRow:
    """The model vector, plus the raw gap the headline MAE uses."""

    values: tuple[float, ...]
    rest_days: int
    is_home: bool
    n_games: int


def usage_units(fga: float, fta: float, tov: float) -> float:
    return fga + FTA_WEIGHT * fta + tov


def visible_logs(logs: Sequence[PlayerLog], as_of: datetime) -> list[PlayerLog]:
    """Newest-first logs whose fact time and ``available_at`` clear ``as_of``."""
    chosen = [log for log in logs if log.event_time < as_of and log.available_at <= as_of]
    chosen.sort(key=lambda log: (log.event_time, log.game_id), reverse=True)
    return chosen


def _mean(values: Sequence[float]) -> float:
    if not values:
        return math.nan
    return sum(values) / len(values)


def _days_since_30(visible_newest_first: Sequence[PlayerLog], game_date: date) -> float:
    for log in visible_newest_first:
        gap = (game_date - log.game_date).days
        if log.points >= POINTS_MARK:
            return float(min(gap, DAYS_SINCE_30_CAP))
        if gap >= DAYS_SINCE_30_CAP:
            return float(DAYS_SINCE_30_CAP)
    return float(DAYS_SINCE_30_CAP)


def _usage_share(
    window: Sequence[PlayerLog],
    team_usage: Mapping[tuple[str, int], float],
) -> float:
    player_sum = 0.0
    team_sum = 0.0
    for log in window:
        team_total = team_usage.get((log.game_id, log.team_id))
        if team_total is None:
            return math.nan
        player_sum += usage_units(log.fga, log.fta, log.tov)
        team_sum += team_total
    if team_sum <= 0.0:
        return math.nan
    return player_sum / team_sum


def opponent_points_allowed(
    games: Sequence[TeamPointsAllowed],
    as_of: datetime,
) -> float:
    """Mean points allowed over the last 15 team games visible at ``as_of``.

    ``games`` is oldest-first. A later ``available_at`` is not part of the mean.
    """
    visible = [game for game in games if game.event_time < as_of and game.available_at <= as_of]
    window = visible[-WINDOW:]
    return _mean([game.points_allowed for game in window])


def build_feature_row(
    prior: Sequence[PlayerLog],
    *,
    game_date: date,
    home_team_id: int,
    away_team_id: int,
    as_of: datetime,
    team_usage: Mapping[tuple[str, int], float],
    team_games: Mapping[int, Sequence[TeamPointsAllowed]],
) -> FeatureRow | None:
    """One vector for a player-game. None means abstain or skip the team.

    ``prior`` may include rows the clock has not cleared. ``visible_logs``
    drops those before any mean is taken. ``team_games`` is every team's
    points-allowed history, oldest-first. The opponent is the other team
    in tonight's game, and only rows visible at ``as_of`` enter the mean.
    """
    visible = visible_logs(prior, as_of)
    if len(visible) < MIN_GAMES:
        return None
    latest = visible[0]
    if latest.team_id == home_team_id:
        is_home = True
    elif latest.team_id == away_team_id:
        is_home = False
    else:
        return None
    rest_days = (game_date - latest.game_date).days
    if rest_days < 0:
        return None

    window = visible[:WINDOW]
    minutes = [log.minutes for log in window if log.minutes is not None]
    values = (
        _mean([log.points for log in visible[:5]]),
        _mean([log.points for log in window]),
        _mean([log.rebounds for log in window]),
        _mean([log.assists for log in window]),
        _mean(minutes),
        1.0 if is_home else 0.0,
        float(min(rest_days, REST_CAP)),
        _usage_share(window, team_usage),
        opponent_points_allowed(
            team_games.get(away_team_id if is_home else home_team_id, ()),
            as_of,
        ),
        _days_since_30(visible, game_date),
    )
    if len(values) != len(FEATURE_NAMES):
        raise RuntimeError("feature vector does not match FEATURE_NAMES")
    return FeatureRow(
        values=values,
        rest_days=rest_days,
        is_home=is_home,
        n_games=len(window),
    )
