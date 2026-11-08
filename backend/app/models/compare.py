"""Holdout cut and the comparison verdict. No model is fit here."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.models.features import REST_CAP

HOLDOUT_FRACTION = 0.2


def holdout_start(dates: Iterable[date], fraction: float = HOLDOUT_FRACTION) -> date:
    """First game date of the last slice. Every row on a date stays together."""
    if not 0.0 < fraction < 1.0:
        raise ValueError(f"fraction must be between 0 and 1, got {fraction}")
    unique = sorted(set(dates))
    if len(unique) < 2:
        raise ValueError("holdout needs at least two game dates")
    n_holdout = round(len(unique) * fraction)
    n_holdout = min(max(n_holdout, 1), len(unique) - 1)
    return unique[-n_holdout]


def in_headline(rest_days: int) -> bool:
    """Raw gaps over the cap are reported, and they are not the acceptance MAE."""
    return rest_days <= REST_CAP


def verdict(
    *,
    headline_games: int,
    xgb_mae: float | None,
    baseline_mae: float | None,
    xgb_brier: float | None,
    baseline_brier: float | None,
) -> str:
    """Acceptance label for one holdout.

    ``refused`` when the headline is fewer than two games.
    ``not_better`` when the baseline MAE is lower or equal.
    ``mae_only`` when MAE improves and no contract was scored.
    ``mixed`` when MAE improves and the residual Brier is worse.
    ``pass`` when MAE improves and the residual Brier is not worse.
    """
    if headline_games < 2 or xgb_mae is None or baseline_mae is None:
        return "refused"
    if xgb_mae >= baseline_mae:
        return "not_better"
    if xgb_brier is None or baseline_brier is None:
        return "mae_only"
    if xgb_brier > baseline_brier:
        return "mixed"
    return "pass"
