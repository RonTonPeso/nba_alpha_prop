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
    covariate_scale,
    date_blocks,
    diagnostic_players,
    diagnostics_pass,
    histogram,
    location_tradeoff,
    ppc_svg,
    row_width,
    sampler_training_rows,
    standardized_covariate,
    tail_probability,
    tradeoff_note,
    tradeoff_svg,
)
from app.models.posterior_model import draws_from, parameter_rows


def test_date_blocks_are_contiguous_and_earliest_first() -> None:
    days = [date(2025, 1, day) for day in range(1, 11)]
    blocks = date_blocks(days, 5)
    assert [len(block) for block in blocks] == [2, 2, 2, 2, 2]
    assert blocks[0] == [date(2025, 1, 1), date(2025, 1, 2)]
    assert blocks[-1] == [date(2025, 1, 9), date(2025, 1, 10)]
    assert [day for block in blocks for day in block] == days


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
    assert diagnostics_pass([("sigma", 1.0, 500), ("tau", 1.0, 500)])


def test_fixed_beta_model_holds_the_slope_at_one() -> None:
    from app.models.posterior_model import points_model

    model = points_model(
        player_ids=[4, 8],
        player_code=np.array([0, 1, 0]),
        xgb_mean=np.array([10.0, 12.0, 11.0]),
        observed=np.array([0.0, 14.0, 10.0]),
        censored=True,
        fixed_beta=True,
    )
    assert "beta" in model.named_vars
    assert "tau" in model.named_vars


def test_wider_tail_when_gamma_scales_the_width() -> None:
    shared = PosteriorDraw(beta=1.0, sigma=2.0, alpha={7: 0.0}, gamma=0.0)
    wider = PosteriorDraw(beta=1.0, sigma=2.0, alpha={7: 0.0}, gamma=1.0)
    shared_probability = tail_probability(
        [shared], player_id=7, xgb_mean=10.0, line=14.0, covariate_z=1.0
    )
    wider_probability = tail_probability(
        [wider], player_id=7, xgb_mean=10.0, line=14.0, covariate_z=1.0
    )
    assert row_width(2.0, 1.0, 1.0) == pytest.approx(2.0 * math.e)
    assert wider_probability > shared_probability


def test_covariate_scale_uses_the_training_rows_only() -> None:
    center, scale = covariate_scale([10.0, 12.0, 14.0])
    assert center == pytest.approx(12.0)
    assert standardized_covariate(12.0, center=center, scale=scale) == pytest.approx(0.0)
    assert standardized_covariate(14.0, center=center, scale=scale) == pytest.approx(1.0)


def test_diagnostic_gate_rejects_an_unmixed_gamma() -> None:
    clean = [("beta", 1.0, 500.0), ("sigma", 1.0, 500.0), ("tau", 1.0, 500.0)]
    assert diagnostics_pass(clean)
    assert not diagnostics_pass([*clean, ("gamma", 1.05, 500.0)])
    assert diagnostics_pass([*clean, ("gamma", 1.0, 500.0)])


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


def test_location_tradeoff_sees_beta_absorbed_by_the_intercepts() -> None:
    means = [10.0, 20.0, 30.0]
    beta = [0.8, 1.0, 1.2, 1.4]
    tau = [1.0, 1.1, 1.2, 1.3]
    alpha = [[-value * mean for mean in means] for value in beta]
    result = location_tradeoff(beta, tau, alpha, means)
    assert result.beta_slope_correlation == pytest.approx(-1.0)
    assert result.mean_slope == pytest.approx(-sum(beta) / len(beta))
    assert result.beta_tau_correlation == pytest.approx(1.0)
    assert "not a separate scale" in tradeoff_note(result)
    svg = tradeoff_svg(beta, tau)
    assert svg.startswith("<svg")
    assert "beta" in svg


def test_location_tradeoff_rejects_a_flat_player_mean() -> None:
    with pytest.raises(ValueError):
        location_tradeoff([1.0, 1.1, 1.2], [0.4, 0.5, 0.6], [[0.0, 0.0]] * 3, [5.0, 5.0])


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


def test_predictive_summary_stops_draws_at_zero() -> None:
    from app.models.posterior_model import predictive_summary

    mean, std, low, mid, high = predictive_summary(
        [-2.0, 0.0, 2.0, 4.0],
        clip_at_zero=True,
    )
    assert mean == 1.5
    assert low == 0.0
    assert mid == 1.0
    assert abs(high - 3.4) < 1e-9
    assert std > 0
    plain, _, _, _, _ = predictive_summary([-2.0, 0.0, 2.0, 4.0], clip_at_zero=False)
    assert plain == 1.0


def test_predictive_draws_include_observation_noise() -> None:
    """Stored std must reflect sigma, not only var(mu). Catches M6 B1."""
    from app.models.posterior_fit import _predictive_draws
    from app.models.posterior_model import predictive_summary

    n = 4000
    beta = np.ones(n)
    # Near-constant location; location-only std would be ~0.
    alpha = np.zeros((n, 1))
    sigma = np.full(n, 6.5)
    gamma = np.zeros(n)
    rng = np.random.default_rng(0)
    draws = _predictive_draws(
        15.0,
        beta=beta,
        alpha=alpha,
        sigma=sigma,
        gamma=gamma,
        slot=0,
        covariate_z=0.0,
        rng=rng,
    )
    _, std, _, _, _ = predictive_summary(draws, clip_at_zero=False)
    assert std > 5.0
    location_only = beta * 15.0 + alpha[:, 0]
    assert float(location_only.std(ddof=1)) < 1e-9


def test_residual_intercept_has_no_slope_on_the_level() -> None:
    from app.models.posterior import residual_intercept

    level = [10.0, 20.0, 15.0, 30.0]
    residual = residual_intercept([1.0, -2.0, 0.5, 3.0], level)
    centered = [value - sum(level) / len(level) for value in level]
    variance = sum(value * value for value in centered)
    slope = sum(value * center for value, center in zip(residual, centered, strict=True)) / variance
    assert abs(slope) < 1e-9


def test_orthogonal_model_needs_a_varying_player_level() -> None:
    from app.models.posterior_model import points_model

    with pytest.raises(ValueError, match="player level"):
        points_model(
            player_ids=[4, 8],
            player_code=np.array([0, 1, 0]),
            xgb_mean=np.array([10.0, 12.0, 11.0]),
            observed=np.array([0.0, 14.0, 10.0]),
            censored=True,
            orthogonal=True,
        )
    model = points_model(
        player_ids=[4, 8],
        player_code=np.array([0, 1, 0]),
        xgb_mean=np.array([10.0, 12.0, 11.0]),
        observed=np.array([0.0, 14.0, 10.0]),
        censored=True,
        orthogonal=True,
        player_level=np.array([10.0, 18.0]),
    )
    assert "alpha" in model.named_vars
    assert "gamma" not in model.named_vars


def test_points_model_uses_a_noncentered_intercept() -> None:
    from app.models.posterior_model import points_model

    model = points_model(
        player_ids=[4, 8],
        player_code=np.array([0, 1, 0]),
        xgb_mean=np.array([10.0, 12.0, 11.0]),
        observed=np.array([9.0, 14.0, 10.0]),
    )
    assert "alpha_raw" in model.named_vars
    assert "alpha" in model.named_vars
    assert "gamma" in model.named_vars


def test_censored_model_shares_sigma_and_stops_at_zero() -> None:
    from app.models.posterior_model import points_model

    model = points_model(
        player_ids=[4, 8],
        player_code=np.array([0, 1, 0]),
        xgb_mean=np.array([10.0, 12.0, 11.0]),
        observed=np.array([0.0, 14.0, 10.0]),
        censored=True,
    )
    assert "gamma" not in model.named_vars
    assert "y" in model.named_vars
    draw = PosteriorDraw(beta=1.0, sigma=2.0, alpha={7: 0.0})
    censored_tail = tail_probability(
        [draw], player_id=7, xgb_mean=10.0, line=14.0, censored_at_zero=True
    )
    plain_tail = tail_probability(
        [draw], player_id=7, xgb_mean=10.0, line=14.0, censored_at_zero=False
    )
    assert censored_tail == plain_tail
    assert (
        tail_probability([draw], player_id=7, xgb_mean=10.0, line=0.0, censored_at_zero=True) == 1.0
    )


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
