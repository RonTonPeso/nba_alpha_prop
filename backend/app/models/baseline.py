"""M3 baseline: a rolling mean with home/away and rest adjustments.

The model is intentionally small. Its job is to force the prediction
and backtest path to exist before XGBoost or PyMC show up. A good
baseline that leaks is worse than a dumb baseline that does not.

Window is the last 15 games, per the roadmap. Fewer than 5 games
abstains. Home/away and rest effects are estimated from those same
prior games, then applied at half strength so the rolling mean is not
shifted by a full venue gap it already partly contains.

The spread is the sample standard deviation of the window, floored so
a constant window still has a band. Quantiles are the normal
approximation of that mean and std. NBA counting stats are not normal.
The band is there because a prediction without one is not allowed to
ship. M6 replaces the distribution.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

MODEL_VERSION = "baseline-m3-v1"
WINDOW = 15
MIN_GAMES = 5
EFFECT_MIN_BUCKET = 3
STD_FLOOR = 0.5
LOW_CONFIDENCE_BELOW = 10
# Standard normal quantiles. Hardcoded so the row can be rebuilt without scipy.
_Z10 = -1.2815515655446004
_Z90 = 1.2815515655446004

PROP_TYPES = ("points", "rebounds", "assists")


@dataclass(frozen=True)
class HistoryGame:
    """One prior game the baseline is allowed to see."""

    game_date: date
    is_home: bool
    team_id: int
    points: float
    rebounds: float
    assists: float


@dataclass(frozen=True)
class Forecast:
    prop_type: str
    mean: float
    std: float
    quantile_10: float
    quantile_50: float
    quantile_90: float
    n_games: int
    low_confidence: bool
    mu_window: float
    home_effect: float
    rest_effect: float
    is_home: bool
    rest_days: int | None
    model_version: str = MODEL_VERSION

    def payload(self) -> dict[str, object]:
        return {
            "distribution": "normal",
            "mu_window": self.mu_window,
            "home_effect": self.home_effect,
            "rest_effect": self.rest_effect,
            "is_home": self.is_home,
            "rest_days": self.rest_days,
            "window": WINDOW,
            "std_floor": STD_FLOOR,
        }


def stat_value(game: HistoryGame, prop_type: str) -> float:
    if prop_type == "points":
        return game.points
    if prop_type == "rebounds":
        return game.rebounds
    if prop_type == "assists":
        return game.assists
    raise ValueError(f"unsupported prop_type {prop_type!r}")


def rest_days_between(later: date, earlier: date) -> int:
    """Calendar days from the previous game to this one. 1 is a back-to-back."""
    return (later - earlier).days


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _bucket_effect(
    values: list[float],
    mask_high: list[bool],
) -> float:
    """Mean(high) - mean(low). Zero unless both buckets have enough games."""
    high = [v for v, flag in zip(values, mask_high, strict=True) if flag]
    low = [v for v, flag in zip(values, mask_high, strict=True) if not flag]
    if len(high) < EFFECT_MIN_BUCKET or len(low) < EFFECT_MIN_BUCKET:
        return 0.0
    return _mean(high) - _mean(low)


def forecast_prop(
    history: list[HistoryGame],
    *,
    prop_type: str,
    is_home: bool,
    rest_days: int | None,
) -> Forecast | None:
    """Forecast one prop from newest-first history. None means abstain.

    ``history[0]`` is the most recent game strictly before prediction time.
    ``rest_days`` is the gap from that game to the game being forecast.
    None means there is no previous game, so the rest term is zero.
    """
    if prop_type not in PROP_TYPES:
        raise ValueError(f"unsupported prop_type {prop_type!r}")
    if len(history) < MIN_GAMES:
        return None

    window = history[:WINDOW]
    values = [stat_value(game, prop_type) for game in window]
    mu = _mean(values)
    home_effect = _bucket_effect(values, [game.is_home for game in window])

    # Rest on a history row is the gap back to the next-older row.
    # `history` may be longer than the 15-game window, so the oldest
    # window game can still see one game further back.
    rest_values: list[float] = []
    rested_flags: list[bool] = []
    for index, game in enumerate(window):
        if index + 1 >= len(history):
            continue
        previous = history[index + 1]
        gap = rest_days_between(game.game_date, previous.game_date)
        if gap <= 0:
            continue
        rest_values.append(values[index])
        rested_flags.append(gap >= 2)
    rest_effect = _bucket_effect(rest_values, rested_flags) if rest_values else 0.0

    adjusted = mu
    if home_effect != 0.0:
        adjusted += 0.5 * home_effect if is_home else -0.5 * home_effect
    if rest_days is not None and rest_days > 0 and rest_effect != 0.0:
        adjusted += 0.5 * rest_effect if rest_days >= 2 else -0.5 * rest_effect
    adjusted = max(0.0, adjusted)

    raw_std = statistics.stdev(values) if len(values) >= 2 else 0.0
    std = max(raw_std, STD_FLOOR)
    return Forecast(
        prop_type=prop_type,
        mean=adjusted,
        std=std,
        quantile_10=max(0.0, adjusted + _Z10 * std),
        quantile_50=adjusted,
        quantile_90=adjusted + _Z90 * std,
        n_games=len(window),
        low_confidence=len(window) < LOW_CONFIDENCE_BELOW,
        mu_window=mu,
        home_effect=home_effect,
        rest_effect=rest_effect,
        is_home=is_home,
        rest_days=rest_days,
    )


def mean_absolute_error(pairs: list[tuple[float, float]]) -> float | None:
    """Mean of |predicted - actual|. None when there is nothing to score."""
    if not pairs:
        return None
    return sum(abs(pred - actual) for pred, actual in pairs) / len(pairs)


def over_hit_rate(trials: list[tuple[float, float, float]]) -> tuple[int, int] | None:
    """Hits and trials for predicted-over vs actual-over.

    Each trial is (predicted_mean, actual, line). Over means ``value >= line``,
    which matches Kalshi "X+" settlement. A tie on the line counts as over.
    None when there are no lines to score.
    """
    if not trials:
        return None
    hits = 0
    for predicted, actual, line in trials:
        predicted_over = predicted >= line
        actual_over = actual >= line
        if predicted_over == actual_over:
            hits += 1
    return hits, len(trials)
