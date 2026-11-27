"""Points posterior around a frozen XGBoost mean.

The likelihood is the starting model in ``docs/provenance/m6-plan.md``.
A player intercept is pooled toward zero. ``beta`` is pooled toward 1.
This module does not sample. The command does, on a seeded subset.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol, TypeVar

from app.backtest.metrics import probability_at_least
from app.models.boost import shipped_mean

DIAGNOSTIC_PLAYERS = 40
DIAGNOSTIC_SEED = 0
BETA_MU = 1.0
BETA_SIGMA = 0.25
TAU_SCALE = 2.0
SIGMA_SCALE = 8.0
SIGMA_FLOOR = 1e-3
RHAT_LIMIT = 1.01
ESS_FLOOR = 400
GAMMA_SIGMA = 0.5


class _DatedPlayer(Protocol):
    @property
    def game_date(self) -> date: ...

    @property
    def player_id(self) -> int: ...


_RowT = TypeVar("_RowT", bound=_DatedPlayer)


@dataclass(frozen=True)
class PosteriorDraw:
    beta: float
    sigma: float
    alpha: dict[int, float]
    gamma: float = 0.0


@dataclass(frozen=True)
class LocationTradeoff:
    """How beta moves with tau and with the player intercepts.

    ``mean_slope`` is the average, over draws, of the least-squares slope of
    the player intercepts on each player's mean booster prediction. A slope
    near the negative of beta means a higher beta is absorbed by lower
    intercepts on high-mean players.
    """

    beta_tau_correlation: float
    beta_slope_correlation: float
    mean_slope: float
    mean_beta: float


def diagnostic_players(
    training_ids: Sequence[int],
    holdout_ids: Sequence[int],
    *,
    n: int = DIAGNOSTIC_PLAYERS,
    seed: int = DIAGNOSTIC_SEED,
) -> list[int]:
    """Seeded subset that has both a training row and a holdout row.

    The sample is sorted so a rerun with the same seed names the same players.
    Fewer eligible players than ``n`` returns every eligible player.
    """
    if n < 1:
        raise ValueError(f"n must be positive, got {n}")
    eligible = sorted(set(training_ids) & set(holdout_ids))
    if len(eligible) <= n:
        return eligible
    chosen = random.Random(seed).sample(eligible, n)
    return sorted(chosen)


def date_blocks(dates: Sequence[date], folds: int) -> list[list[date]]:
    """Contiguous date blocks, earliest first.

    Block 0 is the earliest slice. An expanding out-of-fold fit trains on
    the blocks before the one it predicts, so block 0 has no prediction.
    """
    if folds < 2:
        raise ValueError(f"folds must be at least 2, got {folds}")
    ordered = sorted(set(dates))
    if len(ordered) < folds:
        raise ValueError(f"need at least {folds} dates, got {len(ordered)}")
    blocks: list[list[date]] = [[] for _ in range(folds)]
    for index, day in enumerate(ordered):
        blocks[min(folds - 1, index * folds // len(ordered))].append(day)
    return blocks


def player_index(player_ids: Sequence[int]) -> dict[int, int]:
    """Dense codes in ascending player id order."""
    return {player_id: index for index, player_id in enumerate(sorted(set(player_ids)))}


def covariate_scale(values: Sequence[float]) -> tuple[float, float]:
    """Mean and sample standard deviation of the booster predictions.

    Holdout rows use this pair. They do not use their own mean or spread.
    """
    if len(values) < 2:
        raise ValueError("covariate_scale needs at least two values")
    center = sum(values) / len(values)
    variance = sum((value - center) ** 2 for value in values) / (len(values) - 1)
    scale = math.sqrt(variance)
    if scale < 1e-6:
        raise ValueError("booster predictions do not vary")
    return center, scale


def standardized_covariate(value: float, *, center: float, scale: float) -> float:
    """Training-standardized booster prediction. The training mean sits at 0."""
    if scale <= 0:
        raise ValueError("scale must be positive")
    return (value - center) / scale


def row_width(sigma: float, gamma: float, covariate_z: float) -> float:
    """Width for one row. ``gamma`` of 0 is the shared width ``sigma``."""
    return max(sigma * math.exp(gamma * covariate_z), SIGMA_FLOOR)


def tail_probability(
    draws: Sequence[PosteriorDraw],
    *,
    player_id: int,
    xgb_mean: float,
    line: float,
    covariate_z: float = 0.0,
    censored_at_zero: bool = False,
) -> float:
    """Mean of P(stat >= line) across posterior draws.

    A player missing from a draw keeps intercept 0. That is the booster-only case.
    ``covariate_z`` is the training-standardized booster mean for this row.
    For a normal left-censored at 0, a line at or below 0 has probability 1.
    A line above 0 uses the latent normal's upper tail, because the censored
    mass sits at 0.
    """
    if not draws:
        raise ValueError("tail_probability needs at least one draw")
    if censored_at_zero and line <= 0:
        return 1.0
    total = 0.0
    location = shipped_mean(xgb_mean)
    for draw in draws:
        mu = draw.beta * location + draw.alpha.get(player_id, 0.0)
        total += probability_at_least(mu, row_width(draw.sigma, draw.gamma, covariate_z), line)
    return total / len(draws)


def sampler_training_rows(
    rows: Sequence[_RowT],
    *,
    holdout_on: date,
    player_ids: Sequence[int],
) -> list[_RowT]:
    """Training rows the sampler may see.

    A row on ``holdout_on`` or after it stays out, including when that player
    is in the subset. The caller passes the full example list. Filtering only
    by player id would hand the holdout to NUTS.
    """
    chosen = set(player_ids)
    return [row for row in rows if row.game_date < holdout_on and row.player_id in chosen]


def diagnostics_pass(
    rows: Sequence[tuple[str, float, float]],
    *,
    divergences: int = 0,
) -> bool:
    """True when beta, sigma, and tau mix and the sampler reports no divergences.

    R-hat must be finite and strictly under 1.01. ESS must be finite and
    strictly above 400. A NaN R-hat, which ArviZ returns when a parameter
    does not move, is a failure. ``divergences`` above 0 is a failure even
    when the three rows look clean. A reported ``gamma`` has to clear the
    same bar. A missing ``gamma`` is the shared-width model.
    """
    if divergences < 0:
        raise ValueError(f"divergences must be non-negative, got {divergences}")
    if divergences > 0:
        return False
    needed = {"sigma", "tau"}
    if any(name == "beta" for name, _rhat, _ess in rows):
        needed.add("beta")
    if any(name == "gamma" for name, _rhat, _ess in rows):
        needed.add("gamma")
    seen: set[str] = set()
    for name, rhat, ess in rows:
        if name not in needed:
            continue
        seen.add(name)
        if not math.isfinite(rhat) or not math.isfinite(ess):
            return False
        if rhat >= RHAT_LIMIT or ess <= ESS_FLOOR:
            return False
    return seen == needed


def histogram(values: Sequence[float], *, upper: float = 60.0, width: float = 5.0) -> list[int]:
    """Counts, including the mass outside ``[0, upper)``.

    The first bin is every value below 0. The last bin is every value at or
    above ``upper``. The bins between them are ``width`` wide.
    """
    if upper <= 0 or width <= 0:
        raise ValueError("upper and width must be positive")
    interior = int(upper / width)
    counts = [0] * (interior + 2)
    for value in values:
        if value < 0:
            counts[0] += 1
        elif value >= upper:
            counts[-1] += 1
        else:
            counts[1 + int(value / width)] += 1
    return counts


def ppc_svg(
    observed: Sequence[int],
    predictive: Sequence[float],
    *,
    upper: float = 60.0,
) -> str:
    """Observed counts against the mean posterior predictive count per bin.

    ``observed`` is the histogram that keeps the below-zero bin and the
    overflow bin. The axis labels assume that layout.
    """
    if len(observed) != len(predictive) or len(observed) < 3:
        raise ValueError("observed and predictive histograms must match and include the end bins")
    width = 520
    height = 300
    left = 44
    right = 16
    top = 28
    bottom = 48
    plot_w = width - left - right
    plot_h = height - top - bottom
    peak = max(max(observed), max(predictive), 1)
    bar = plot_w / len(observed)
    interior = len(observed) - 2
    bin_width = upper / interior

    def y_of(count: float) -> float:
        return top + (1.0 - count / peak) * plot_h

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img">'
        ),
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        (
            f'<text x="{width / 2:.0f}" y="18" text-anchor="middle" '
            'font-family="sans-serif" font-size="13" fill="#111827">'
            "Points: observed vs posterior predictive</text>"
        ),
    ]
    for index, (obs, pred) in enumerate(zip(observed, predictive, strict=True)):
        x = left + index * bar
        parts.append(
            f'<rect x="{x:.1f}" y="{y_of(obs):.1f}" width="{bar * 0.45:.1f}" '
            f'height="{top + plot_h - y_of(obs):.1f}" fill="#1d4ed8" fill-opacity="0.75"/>'
        )
        parts.append(
            f'<rect x="{x + bar * 0.45:.1f}" y="{y_of(pred):.1f}" width="{bar * 0.45:.1f}" '
            f'height="{top + plot_h - y_of(pred):.1f}" fill="#b45309" fill-opacity="0.75"/>'
        )
        label = _bin_label(index, len(observed), bin_width)
        if label:
            parts.append(
                f'<text x="{x + bar / 2:.1f}" y="{height - 28}" text-anchor="middle" '
                'font-family="sans-serif" font-size="10" fill="#374151">'
                f"{label}</text>"
            )
    parts.append(
        f'<text x="4" y="{top + 8:.0f}" font-family="sans-serif" font-size="10" fill="#374151">'
        f"{peak:.0f}</text>"
    )
    parts.append(
        f'<text x="4" y="{top + plot_h:.0f}" font-family="sans-serif" font-size="10" '
        'fill="#374151">0</text>'
    )
    parts.append(
        f'<text x="48" y="{height - 8}" font-family="sans-serif" font-size="11" fill="#1d4ed8">'
        "observed</text>"
    )
    parts.append(
        f'<text x="120" y="{height - 8}" font-family="sans-serif" font-size="11" fill="#b45309">'
        "posterior predictive</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)


def residual_intercept(raw: Sequence[float], level: Sequence[float]) -> list[float]:
    """Drop the linear piece of ``raw`` along ``level``.

    The slope of the result on ``level`` is zero. A flat level has nothing
    to remove and raises.
    """
    if len(raw) != len(level) or len(raw) < 2:
        raise ValueError("raw and level must be the same length, at least two")
    centered = _centered(level)
    variance = sum(value * value for value in centered)
    if variance == 0.0:
        raise ValueError("player levels do not vary")
    slope = sum(value * center for value, center in zip(raw, centered, strict=True)) / variance
    return [value - slope * center for value, center in zip(raw, centered, strict=True)]


def location_tradeoff(
    beta: Sequence[float],
    tau: Sequence[float],
    alpha: Sequence[Sequence[float]],
    player_mean: Sequence[float],
) -> LocationTradeoff:
    """Correlation of beta with tau, and of beta with the intercept slope."""
    if not (len(beta) == len(tau) == len(alpha)):
        raise ValueError("beta, tau, and alpha must have one entry per draw")
    if len(beta) < 3:
        raise ValueError("location_tradeoff needs at least three draws")
    if len(player_mean) < 2:
        raise ValueError("location_tradeoff needs at least two players")
    centered = _centered(player_mean)
    variance = sum(value * value for value in centered)
    if variance == 0.0:
        raise ValueError("player means do not vary")
    slopes: list[float] = []
    for draw in alpha:
        if len(draw) != len(centered):
            raise ValueError("each alpha draw must have one value per player")
        slopes.append(
            sum(value * center for value, center in zip(draw, centered, strict=True)) / variance
        )
    slope_energy = math.sqrt(sum(value * value for value in _centered(slopes)))
    slope_correlation = float("nan") if slope_energy < 1e-8 else _pearson(beta, slopes)
    return LocationTradeoff(
        beta_tau_correlation=_pearson(beta, tau),
        beta_slope_correlation=slope_correlation,
        mean_slope=sum(slopes) / len(slopes),
        mean_beta=sum(beta) / len(beta),
    )


def tradeoff_note(result: LocationTradeoff) -> str:
    """One sentence on whether the intercepts are absorbing beta."""
    correlation = result.beta_slope_correlation
    if not math.isfinite(correlation):
        return "The correlation of beta with the intercept slope is not defined."
    if correlation <= -0.8:
        return (
            "Beta and the player intercepts move together. A higher beta is absorbed "
            "by lower intercepts on high-mean players, so tau is not a separate scale "
            "in this sample."
        )
    return (
        "The draws do not show the player intercepts absorbing beta. "
        f"The correlation of beta with that slope is {correlation:.3f}."
    )


def tradeoff_svg(beta: Sequence[float], tau: Sequence[float], *, limit: int = 400) -> str:
    """Thinned scatter of posterior draws, beta on the horizontal axis."""
    if len(beta) != len(tau) or len(beta) < 2:
        raise ValueError("beta and tau must be the same length and non-trivial")
    if limit < 2:
        raise ValueError(f"limit must be at least 2, got {limit}")
    step = max(len(beta) // limit, 1)
    xs = [float(beta[index]) for index in range(0, len(beta), step)][:limit]
    ys = [float(tau[index]) for index in range(0, len(tau), step)][:limit]
    width = 480
    height = 320
    left = 52
    right = 16
    top = 28
    bottom = 40
    plot_w = width - left - right
    plot_h = height - top - bottom
    x_span = max(xs) - min(xs) or 1.0
    y_span = max(ys) - min(ys) or 1.0
    x_pad = x_span * 0.05
    y_pad = y_span * 0.05
    x0 = min(xs) - x_pad
    y0 = min(ys) - y_pad
    x_span += 2 * x_pad
    y_span += 2 * y_pad

    def x_of(value: float) -> float:
        return left + (value - x0) / x_span * plot_w

    def y_of(value: float) -> float:
        return top + (1.0 - (value - y0) / y_span) * plot_h

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img">'
        ),
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        (
            f'<text x="{width / 2:.0f}" y="18" text-anchor="middle" '
            'font-family="sans-serif" font-size="13" fill="#111827">'
            "Posterior draws: beta against tau</text>"
        ),
        (f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" ' 'stroke="#d1d5db"/>'),
        (
            f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" '
            'stroke="#d1d5db"/>'
        ),
    ]
    for x_value, y_value in zip(xs, ys, strict=True):
        parts.append(
            f'<circle cx="{x_of(x_value):.1f}" cy="{y_of(y_value):.1f}" r="2.2" '
            'fill="#1d4ed8" fill-opacity="0.35"/>'
        )
    parts.append(
        f'<text x="{left}" y="{top + 12}" font-family="sans-serif" font-size="10" '
        f'fill="#374151">{max(ys):.2f}</text>'
    )
    parts.append(
        f'<text x="{left}" y="{top + plot_h - 4}" font-family="sans-serif" font-size="10" '
        f'fill="#374151">{min(ys):.2f}</text>'
    )
    parts.append(
        f'<text x="{left}" y="{height - 8}" font-family="sans-serif" font-size="11" '
        f'fill="#374151">beta {min(xs):.2f}</text>'
    )
    parts.append(
        f'<text x="{left + plot_w - 70}" y="{height - 8}" font-family="sans-serif" '
        f'font-size="11" fill="#374151">beta {max(xs):.2f}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _centered(values: Sequence[float]) -> list[float]:
    center = sum(values) / len(values)
    return [value - center for value in values]


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 3:
        raise ValueError("correlation needs two equal series of at least three values")
    centered_left = _centered(left)
    centered_right = _centered(right)
    covariance = sum(a * b for a, b in zip(centered_left, centered_right, strict=True))
    left_energy = math.sqrt(sum(value * value for value in centered_left))
    right_energy = math.sqrt(sum(value * value for value in centered_right))
    if left_energy == 0.0 or right_energy == 0.0:
        return float("nan")
    return covariance / (left_energy * right_energy)


def _bin_label(index: int, count: int, bin_width: float) -> str:
    """Tick text for the end bins and for 0 and the middle of the interior."""
    if index == 0:
        return "<0"
    if index == count - 1:
        return f"{(count - 2) * bin_width:.0f}+"
    start = (index - 1) * bin_width
    if start == 0 or abs(start - (count - 2) * bin_width / 2) < 1e-9:
        return f"{start:.0f}"
    return ""
