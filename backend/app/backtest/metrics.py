"""Probability scores for a stored normal forecast.

The M3 row holds a mean and a standard deviation, not a probability.
M4 turns that placeholder normal into P(stat >= line) and scores the
probability. The normal is still a placeholder. M6 is the posterior.

Brier and log loss are checked against hand-computed values in
``tests/test_calibration.py``. A wrong formula should fail there
before it ever lands in a report.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Log loss is infinite at 0 and 1. Clip only the log, not the Brier score.
LOG_LOSS_EPS = 1e-6


@dataclass(frozen=True)
class ProbTrial:
    """One Kalshi contract scored against the box score.

    ``outcome`` is 1 when the stat is >= the line, else 0.
    ``market_probability`` is the yes mid when a snapshot was visible
    at the prediction clock, else None.
    """

    probability: float
    outcome: int
    market_probability: float | None


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_predicted: float | None
    realized_rate: float | None


@dataclass(frozen=True)
class DisagreementScore:
    """How often the model's side of a quote was the side that happened.

    This is a count of contracts. It is not a payout.
    """

    quoted: int
    unquoted: int
    compared: int
    hits: int


def probability_at_least(mean: float, std: float, line: float) -> float:
    """P(X >= line) for X ~ Normal(mean, std), via the standard-normal cdf."""
    if std <= 0:
        raise ValueError(f"std must be positive, got {std}")
    z = (line - mean) / std
    cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return 1.0 - cdf


def _check_pair(probability: float, outcome: int) -> None:
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"probability must be in [0, 1], got {probability}")
    if outcome not in (0, 1):
        raise ValueError(f"outcome must be 0 or 1, got {outcome}")


def brier_score(pairs: list[tuple[float, int]]) -> float:
    """Mean squared error of a probability against a 0/1 outcome."""
    if not pairs:
        raise ValueError("brier_score needs at least one pair")
    total = 0.0
    for probability, outcome in pairs:
        _check_pair(probability, outcome)
        total += (probability - outcome) ** 2
    return total / len(pairs)


def log_loss(pairs: list[tuple[float, int]], *, eps: float = LOG_LOSS_EPS) -> float:
    """Mean binary log loss. Probabilities are clipped to [eps, 1 - eps]."""
    if not pairs:
        raise ValueError("log_loss needs at least one pair")
    if not 0.0 < eps < 0.5:
        raise ValueError(f"eps must be in (0, 0.5), got {eps}")
    total = 0.0
    for probability, outcome in pairs:
        _check_pair(probability, outcome)
        clipped = min(max(probability, eps), 1.0 - eps)
        total += -(outcome * math.log(clipped) + (1 - outcome) * math.log(1.0 - clipped))
    return total / len(pairs)


def calibration_bins(
    pairs: list[tuple[float, int]],
    *,
    n_bins: int = 10,
) -> list[CalibrationBin]:
    """Equal-width bins on [0, 1]. The last bin includes 1.0.

    Empty bins stay in the list so a report can show where the model
    never placed a probability.
    """
    if n_bins < 1:
        raise ValueError(f"n_bins must be positive, got {n_bins}")
    counts = [0] * n_bins
    sum_p = [0.0] * n_bins
    sum_y = [0] * n_bins
    for probability, outcome in pairs:
        _check_pair(probability, outcome)
        index = n_bins - 1 if probability >= 1.0 else min(int(probability * n_bins), n_bins - 1)
        counts[index] += 1
        sum_p[index] += probability
        sum_y[index] += outcome
    bins: list[CalibrationBin] = []
    for index in range(n_bins):
        lower = index / n_bins
        upper = (index + 1) / n_bins
        count = counts[index]
        if count == 0:
            bins.append(
                CalibrationBin(
                    lower=lower,
                    upper=upper,
                    count=0,
                    mean_predicted=None,
                    realized_rate=None,
                )
            )
            continue
        bins.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=count,
                mean_predicted=sum_p[index] / count,
                realized_rate=sum_y[index] / count,
            )
        )
    return bins


def calibration_error(bins: list[CalibrationBin]) -> float | None:
    """Count-weighted mean |realized rate - mean predicted probability|.

    Empty bins are left out. None when every bin is empty.
    """
    total = sum(item.count for item in bins)
    if total == 0:
        return None
    gap = 0.0
    for item in bins:
        if item.count == 0 or item.mean_predicted is None or item.realized_rate is None:
            continue
        gap += item.count * abs(item.realized_rate - item.mean_predicted)
    return gap / total


def disagreement_score(trials: list[ProbTrial]) -> DisagreementScore:
    """Count contracts where the model and the mid pick different sides.

    A contract with no mid is unquoted. A contract whose probability
    equals the mid is quoted and not compared. A hit is the outcome
    matching the side the model put above the mid.
    """
    quoted = 0
    unquoted = 0
    compared = 0
    hits = 0
    for trial in trials:
        _check_pair(trial.probability, trial.outcome)
        if trial.market_probability is None:
            unquoted += 1
            continue
        _check_pair(trial.market_probability, 1)
        quoted += 1
        if trial.probability == trial.market_probability:
            continue
        compared += 1
        model_over = trial.probability > trial.market_probability
        happened_over = trial.outcome == 1
        if model_over == happened_over:
            hits += 1
    return DisagreementScore(
        quoted=quoted,
        unquoted=unquoted,
        compared=compared,
        hits=hits,
    )


def _pairs(trials: list[ProbTrial]) -> list[tuple[float, int]]:
    return [(trial.probability, trial.outcome) for trial in trials]


def probability_section(
    trials: list[ProbTrial],
    *,
    chart_name: str,
) -> tuple[list[str], list[CalibrationBin] | None]:
    """Markdown lines for the probability block, plus bins when a chart is due."""
    if not trials:
        return (
            [
                "Brier score: not scored (no contract had a forecast and a line).",
                "Log loss: not scored.",
                "Calibration error: not scored.",
                "Quoted mids at or before 16:00 UTC: 0.",
                (
                    "No snapshot was eligible, or no forecast was scored. "
                    "ADR-3 records that the historical backfill has settlements "
                    "and does not have the book from before this system polled."
                ),
            ],
            None,
        )

    pairs = _pairs(trials)
    brier = brier_score(pairs)
    loss = log_loss(pairs)
    bins = calibration_bins(pairs)
    error = calibration_error(bins)
    disagreement = disagreement_score(trials)
    lines = [
        (
            f"Brier score: {brier:.6f} on {len(trials)} contracts. "
            "Mean squared error of P(stat >= line) against the 0/1 outcome."
        ),
        (
            f"Log loss: {loss:.6f} on {len(trials)} contracts. "
            f"Probabilities are clipped to [{LOG_LOSS_EPS:g}, {1 - LOG_LOSS_EPS:g}] "
            "before the logarithm. Brier uses the unclipped probability."
        ),
        (
            "P(stat >= line) is the upper tail of the normal stored on the "
            "prediction. That normal is the M3 placeholder, not a posterior."
        ),
        (
            "Calibration error: "
            + (f"{error:.6f}." if error is not None else "not scored.")
            + " Count-weighted mean absolute gap between the realized over rate "
            "and the mean predicted probability in the bin. Empty bins are left out."
        ),
        "",
        "Equal-width bins on [0, 1]. The last bin includes 1.",
        "",
        "| bin | n | mean predicted | realized over rate |",
        "| --- | --- | --- | --- |",
    ]
    for item in bins:
        predicted = "" if item.mean_predicted is None else f"{item.mean_predicted:.3f}"
        realized = "" if item.realized_rate is None else f"{item.realized_rate:.3f}"
        lines.append(
            f"| {item.lower:.1f} to {item.upper:.1f} | {item.count} | {predicted} | {realized} |"
        )
    lines.extend(
        [
            "",
            f"![Reliability diagram]({chart_name})",
            "",
            f"Quoted mids at or before 16:00 UTC: {disagreement.quoted}.",
            f"Contracts with no usable pre-tip quote: {disagreement.unquoted}.",
            (
                "The quote is (yes_bid + yes_ask) / 2 from the latest snapshot "
                "whose quoted_at and ingested_at are both at or before the "
                "prediction clock. A one-sided or crossed book is skipped. "
                "last_price is not the quote."
            ),
        ]
    )
    if disagreement.compared == 0:
        lines.append(
            "Disagreement: not scored. No contract had a model probability "
            "different from a visible mid."
        )
    else:
        rate = disagreement.hits / disagreement.compared
        lines.append(
            f"Disagreement: the side the model priced above the mid happened "
            f"on {disagreement.hits}/{disagreement.compared} = {rate:.3f} contracts. "
            "This is a count of outcomes. It is not a payout, and it is not "
            "a claim that the forecast has an edge."
        )
    return lines, bins
