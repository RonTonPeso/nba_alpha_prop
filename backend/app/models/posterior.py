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


def player_index(player_ids: Sequence[int]) -> dict[int, int]:
    """Dense codes in ascending player id order."""
    return {player_id: index for index, player_id in enumerate(sorted(set(player_ids)))}


def tail_probability(
    draws: Sequence[PosteriorDraw],
    *,
    player_id: int,
    xgb_mean: float,
    line: float,
) -> float:
    """Mean of P(stat >= line) across posterior draws.

    A player missing from a draw keeps intercept 0. That is the booster-only case.
    """
    if not draws:
        raise ValueError("tail_probability needs at least one draw")
    total = 0.0
    location = shipped_mean(xgb_mean)
    for draw in draws:
        sigma = max(draw.sigma, SIGMA_FLOOR)
        mu = draw.beta * location + draw.alpha.get(player_id, 0.0)
        total += probability_at_least(mu, sigma, line)
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
    when the three rows look clean.
    """
    if divergences < 0:
        raise ValueError(f"divergences must be non-negative, got {divergences}")
    if divergences > 0:
        return False
    needed = {"beta", "sigma", "tau"}
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
