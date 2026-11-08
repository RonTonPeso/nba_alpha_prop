"""Holdout rule, verdict, and the fixed booster. No database."""

from datetime import date

from app.models.boost import fit_regressor, predict, residual_std, shap_top, shipped_mean
from app.models.compare import holdout_start, in_headline, verdict


def test_holdout_keeps_a_date_on_one_side() -> None:
    dates = [date(2026, 1, day) for day in range(1, 11)]
    start = holdout_start(dates + dates, 0.2)
    assert start == date(2026, 1, 9)


def test_headline_excludes_a_gap_over_14() -> None:
    assert in_headline(14)
    assert not in_headline(15)


def test_verdict_refuses_one_game_and_marks_a_worse_brier_as_mixed() -> None:
    assert (
        verdict(
            headline_games=1,
            xgb_mae=1.0,
            baseline_mae=2.0,
            xgb_brier=0.1,
            baseline_brier=0.2,
        )
        == "refused"
    )
    assert (
        verdict(
            headline_games=4,
            xgb_mae=1.0,
            baseline_mae=2.0,
            xgb_brier=0.3,
            baseline_brier=0.2,
        )
        == "mixed"
    )
    assert (
        verdict(
            headline_games=4,
            xgb_mae=1.0,
            baseline_mae=2.0,
            xgb_brier=None,
            baseline_brier=None,
        )
        == "mae_only"
    )
    assert (
        verdict(
            headline_games=4,
            xgb_mae=3.0,
            baseline_mae=2.0,
            xgb_brier=0.1,
            baseline_brier=0.2,
        )
        == "not_better"
    )


def test_shap_ranks_the_column_the_fit_used() -> None:
    features = [[float(index), 0.0] for index in range(40)]
    target = [float(index) for index in range(40)]
    model = fit_regressor(features, target)
    predicted = predict(model, features)
    assert residual_std(target, predicted) < 1
    ranked = shap_top(model, [features[-1]], ("used", "unused"))
    assert ranked[0][0][0] == "used"
    assert shipped_mean(-3) == 0
