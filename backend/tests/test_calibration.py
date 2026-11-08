"""Hand-computed checks for Brier, log loss, bins, and the normal tail.

The constants below are the arithmetic, not a second call into the
function under test. The normal tail at z=1 is the published value
0.15865525393145707.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.backtest.metrics import (
    LOG_LOSS_EPS,
    ProbTrial,
    brier_score,
    calibration_bins,
    calibration_error,
    disagreement_score,
    log_loss,
    probability_at_least,
    probability_section,
)
from app.backtest.plots import reliability_svg
from app.backtest.quotes import yes_mid
from app.backtest.run import ReplaySummary, render_report, synthetic_week_summary

# Published standard-normal upper tail at z = 1.
_NORMAL_TAIL_AT_1 = 0.15865525393145707


def test_probability_matches_the_standard_normal_tail() -> None:
    assert probability_at_least(20.0, 5.0, 20.0) == 0.5
    assert probability_at_least(20.0, 5.0, 25.0) == _NORMAL_TAIL_AT_1
    # z = -1 is the complementary tail.
    assert probability_at_least(20.0, 5.0, 15.0) == 1.0 - _NORMAL_TAIL_AT_1


def test_brier_on_three_hand_computed_pairs() -> None:
    # (1-1)^2 = 0, (0-0)^2 = 0, (0.5-1)^2 = 0.25. Mean is 0.25/3.
    score = brier_score([(1.0, 1), (0.0, 0), (0.5, 1)])
    assert score == 0.25 / 3


def test_log_loss_on_two_hand_computed_pairs() -> None:
    # y=1, p=0.8 -> -log(0.8). y=0, p=0.8 -> -log(0.2).
    expected = (-math.log(0.8) + -math.log(0.2)) / 2
    assert log_loss([(0.8, 1), (0.8, 0)]) == pytest.approx(expected)


def test_log_loss_clips_zero_and_one() -> None:
    clipped = -math.log(LOG_LOSS_EPS)
    assert log_loss([(0.0, 1)]) == pytest.approx(clipped)
    # 1 - (1 - eps) is not bit-identical to eps, so the complement clip
    # is compared loosely against the same published magnitude.
    assert log_loss([(1.0, 0)]) == pytest.approx(clipped)
    # Brier does not clip. A confident miss is exactly 1.
    assert brier_score([(0.0, 1)]) == 1.0


def test_equal_width_bins_and_error() -> None:
    pairs = [(0.05, 0), (0.05, 0), (0.95, 1), (0.95, 1)]
    bins = calibration_bins(pairs, n_bins=10)
    assert bins[0].count == 2
    assert bins[0].mean_predicted == 0.05
    assert bins[0].realized_rate == 0.0
    assert bins[9].count == 2
    assert bins[9].mean_predicted == 0.95
    assert bins[9].realized_rate == 1.0
    assert all(item.count == 0 for item in bins[1:9])
    # |0 - 0.05| and |1 - 0.95|, weighted equally. Error is 0.05.
    assert calibration_error(bins) == pytest.approx(0.05)


def test_probability_one_lands_in_the_last_bin() -> None:
    bins = calibration_bins([(1.0, 1)], n_bins=10)
    assert bins[9].count == 1
    assert bins[0].count == 0


def test_disagreement_skips_ties_and_missing_quotes() -> None:
    trials = [
        ProbTrial(0.7, 1, 0.4),  # model over, happened over
        ProbTrial(0.7, 0, 0.4),  # model over, happened under
        ProbTrial(0.4, 1, 0.4),  # equal, not compared
        ProbTrial(0.2, 0, None),  # no quote
    ]
    score = disagreement_score(trials)
    assert score.quoted == 3
    assert score.unquoted == 1
    assert score.compared == 2
    assert score.hits == 1


def test_yes_mid_rejects_one_sided_and_crossed_books() -> None:
    assert yes_mid(0.20, 0.30) == 0.25
    assert yes_mid(0.20, None) is None
    assert yes_mid(None, 0.30) is None
    assert yes_mid(0.60, 0.40) is None
    assert yes_mid(0.20, 0.20) == 0.20


def test_reliability_svg_draws_a_point_for_a_filled_bin() -> None:
    bins = calibration_bins([(0.25, 0)] * 35, n_bins=10)
    svg = reliability_svg(bins)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert 'stroke-dasharray="4 4"' in svg
    assert "<circle " in svg


def test_empty_forecast_report_does_not_call_november_too_early() -> None:
    summary = ReplaySummary(start=date(2025, 11, 1), end=date(2025, 11, 30))
    summary.games_seen = 219
    summary.forecasts = 0
    text, svg = render_report(summary, chart_name="unused.svg")
    assert "No forecast was produced" in text
    assert "earlier month" not in text
    assert "ADR-3" not in text
    assert "Games with a scored contract: 0." in text
    assert svg is None


def test_ci_smoke_synthetic_week_has_known_brier() -> None:
    """Five players by seven days. The value is locked. The gap is not a failure.

    Every probability is 0.25 and every outcome is 0, so the calibration
    error is 0.25. A gate that failed the job on that gap would reject
    this fixture, and it would also reject a noisy real week of the same
    size. The smoke test checks the arithmetic.
    """
    summary = synthetic_week_summary()
    assert len(summary.prob_trials) == 5 * 7
    text, svg = render_report(summary, chart_name="m4-calibration-synthetic.svg")
    assert "Brier score: 0.062500 on 35 contracts." in text
    assert "SYNTHETIC." in text
    assert "Predicted under (mean < line): 35/35 = 1.000." in text
    assert "Over means predicted mean >= line and actual stat >= line." not in text
    assert "typed fixture" in text
    assert svg is not None
    assert "<circle " in svg
    lines, bins = probability_section(summary.prob_trials, chart_name="ignored.svg")
    assert bins is not None
    assert calibration_error(bins) == 0.25
    assert any("0.062500" in line for line in lines)
