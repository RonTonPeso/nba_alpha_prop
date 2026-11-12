"""Subset rule, tail probability, diagnostic gate, and draw alignment. No sampler."""

import math
import warnings
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pytest

from app.models.posterior import (
    PosteriorDraw,
    diagnostic_players,
    diagnostics_pass,
    histogram,
    ppc_svg,
    sampler_training_rows,
    tail_probability,
)
from app.models.posterior_model import draws_from, parameter_rows


def test_diagnostic_players_are_stable_and_stay_inside_both_sets() -> None:
    training = list(range(100))
    holdout = list(range(50, 150))
    first = diagnostic_players(training, holdout, n=40, seed=0)
    second = diagnostic_players(training, holdout, n=40, seed=0)
    assert first == second
    assert len(first) == 40
    assert set(first) <= set(training)
    assert set(first) <= set(holdout)
    assert first == sorted(first)


def test_tail_probability_at_the_mean_is_one_half() -> None:
    draw = PosteriorDraw(beta=1.0, sigma=1.0, alpha={7: 0.0})
    probability = tail_probability([draw], player_id=7, xgb_mean=10.0, line=10.0)
    assert probability == 0.5


def test_tail_probability_moves_when_beta_or_alpha_moves() -> None:
    base = PosteriorDraw(beta=1.0, sigma=2.0, alpha={7: 0.0})
    higher_beta = PosteriorDraw(beta=1.2, sigma=2.0, alpha={7: 0.0})
    higher_alpha = PosteriorDraw(beta=1.0, sigma=2.0, alpha={7: 3.0})
    base_probability = tail_probability([base], player_id=7, xgb_mean=10.0, line=12.0)
    assert tail_probability([higher_beta], player_id=7, xgb_mean=10.0, line=12.0) > base_probability
    assert (
        tail_probability([higher_alpha], player_id=7, xgb_mean=10.0, line=12.0) > base_probability
    )


def test_missing_player_uses_a_zero_intercept() -> None:
    present = PosteriorDraw(beta=1.0, sigma=1.0, alpha={7: 5.0})
    missing = tail_probability([present], player_id=9, xgb_mean=10.0, line=10.0)
    known = tail_probability([present], player_id=7, xgb_mean=10.0, line=10.0)
    assert missing == 0.5
    assert known > missing


def test_diagnostic_gate_needs_all_three_parameters() -> None:
    assert diagnostics_pass([("beta", 1.0, 500), ("sigma", 1.0, 500), ("tau", 1.0, 500)])
    assert not diagnostics_pass([("beta", 1.02, 500), ("sigma", 1.0, 500), ("tau", 1.0, 500)])
    assert not diagnostics_pass([("beta", 1.0, 500), ("sigma", 1.0, 500)])


def test_diagnostic_gate_rejects_nan_and_a_single_failure() -> None:
    nan = float("nan")
    clean = [("beta", 1.0, 500.0), ("sigma", 1.0, 500.0), ("tau", 1.0, 500.0)]
    assert not diagnostics_pass([("beta", 1.0, 500), ("sigma", 1.0, 500), ("tau", nan, 800)])
    assert not diagnostics_pass([("beta", 1.0, 500), ("sigma", 1.0, 500), ("tau", 1.0, nan)])
    assert not diagnostics_pass([("beta", 1.0, 400), ("sigma", 1.0, 500), ("tau", 1.0, 500)])
    assert not diagnostics_pass([("beta", 1.0, 500), ("sigma", 1.0, 500), ("tau", 1.0, 28)])
    assert not diagnostics_pass(clean, divergences=1)


def test_sampler_rows_exclude_the_holdout_date() -> None:
    @dataclass(frozen=True)
    class Row:
        game_date: date
        player_id: int

    rows = [
        Row(date(2025, 12, 4), 1),
        Row(date(2025, 12, 5), 1),
        Row(date(2025, 12, 4), 2),
    ]
    kept = sampler_training_rows(rows, holdout_on=date(2025, 12, 5), player_ids=[1])
    assert kept == [Row(date(2025, 12, 4), 1)]


def test_histogram_keeps_mass_outside_the_point_range() -> None:
    counts = histogram([-1.0, 0.0, 59.9, 60.0])
    assert counts[0] == 1
    assert counts[-1] == 1
    assert sum(counts) == 4


def test_ppc_svg_rejects_a_mismatched_histogram() -> None:
    observed = histogram([1, 6, 11])
    with pytest.raises(ValueError):
        ppc_svg(observed, [float(count) for count in observed[:-1]])


def test_ppc_svg_labels_the_low_bin() -> None:
    observed = histogram([-3.0, 4.0])
    svg = ppc_svg(observed, [float(count) for count in observed])
    assert svg.startswith("<svg")
    assert "<0" in svg
    assert "60+" in svg
    assert "observed" in svg


def test_draws_from_follows_the_player_coordinate() -> None:
    import arviz as az

    idata = az.from_dict(
        posterior={
            "beta": np.array([[1.0, 2.0]]),
            "sigma": np.array([[0.5, 0.6]]),
            "alpha": np.array([[[10.0, 30.0], [11.0, 31.0]]]),
        },
        dims={"alpha": ["player"]},
        coords={"player": [4, 8]},
    )
    draws = draws_from(idata, [4, 8])
    assert draws[0].alpha == {4: 10.0, 8: 30.0}
    assert draws[1].beta == 2.0
    with pytest.raises(ValueError):
        draws_from(idata, [8, 4])


def test_parameter_rows_keep_rhat_finer_than_two_decimals() -> None:
    import arviz as az

    rng = np.random.default_rng(0)
    beta = np.concatenate(
        [rng.normal(0.0, 1.0, size=(1, 400)), rng.normal(0.15, 1.0, size=(1, 400))]
    )
    sigma = np.abs(beta) + 0.1
    tau = np.abs(beta) + 0.2
    idata = az.from_dict(posterior={"beta": beta, "sigma": sigma, "tau": tau})
    rows = {name: (rhat, ess) for name, rhat, ess in parameter_rows(idata)}
    rounded: Any = az.summary(idata, var_names=["beta"])
    assert rows["beta"][0] != pytest.approx(float(rounded.loc["beta", "r_hat"]))


def test_a_stuck_tau_fails_the_gate_through_arviz() -> None:
    import arviz as az

    rng = np.random.default_rng(1)
    tau = np.full((2, 80), 1.3)
    beta = rng.normal(size=(2, 80))
    sigma = np.abs(rng.normal(size=(2, 80))) + 0.2
    idata = az.from_dict(posterior={"beta": beta, "sigma": sigma, "tau": tau})
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="invalid value encountered in scalar divide",
            category=RuntimeWarning,
        )
        rows = parameter_rows(idata)
    by_name = {name: (rhat, ess) for name, rhat, ess in rows}
    assert math.isnan(by_name["tau"][0])
    assert not diagnostics_pass(rows)
