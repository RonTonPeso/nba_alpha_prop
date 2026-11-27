"""Sample the points model.

This is the starting likelihood from ``docs/provenance/m6-plan.md``.
The agent typed it for the M6 diagnostic. The intercept is non-centered.
It is not a settled model and it is not an ADR. Ronnie replaces the
priors before an acceptance fit.
The parameter names ``beta``, ``sigma``, and ``tau`` are what the gate reads.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pymc as pm

from app.models.posterior import (
    BETA_MU,
    BETA_SIGMA,
    GAMMA_SIGMA,
    SIGMA_SCALE,
    TAU_SCALE,
    PosteriorDraw,
)

TARGET_ACCEPT = 0.9
POSTERIOR_VERSION = "pymc-m6-v1"


def predictive_summary(
    latent: Any,
    *,
    clip_at_zero: bool,
) -> tuple[float, float, float, float, float]:
    """Mean, sample sd, and 10/50/90 of one row's posterior predictive draws.

    With ``clip_at_zero``, each draw is the latent normal stopped at 0.
    That is the predictive distribution of the censored points model.
    """
    draws = np.asarray(latent, dtype=np.float64).reshape(-1)
    if clip_at_zero:
        draws = np.maximum(draws, 0.0)
    if draws.size < 2:
        raise ValueError("predictive_summary needs at least two draws")
    low, mid, high = np.quantile(draws, [0.1, 0.5, 0.9])
    return (
        float(draws.mean()),
        float(draws.std(ddof=1)),
        float(low),
        float(mid),
        float(high),
    )


def points_model(
    *,
    player_ids: list[int],
    player_code: Any,
    xgb_mean: Any,
    observed: Any,
    covariate_z: Any = None,
    censored: bool = False,
    orthogonal: bool = False,
    player_level: Any = None,
    fixed_beta: bool = False,
) -> Any:
    """Non-centered intercept around the booster mean.

    ``alpha`` equals ``tau`` times a standard normal. The priors on
    ``beta``, ``tau``, and ``sigma`` are unchanged unless ``fixed_beta``
    is true, in which case ``beta`` is the constant 1. With ``censored``
    false, the row width is ``sigma * exp(gamma * z)`` and the likelihood
    is a plain normal. With ``censored`` true, the width is the shared
    ``sigma`` and the likelihood is a normal left-censored at 0.
    With ``orthogonal`` true, the intercept has no slope on ``player_level``.
    """
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("player_ids must be unique")
    if not (len(player_code) == len(xgb_mean) == len(observed)):
        raise ValueError("training columns must be the same length")
    if censored and np.any(np.asarray(observed, dtype=np.float64) < 0):
        raise ValueError("a censored points likelihood cannot see a negative observation")
    if not censored:
        if covariate_z is None:
            covariate_z = np.zeros(len(observed), dtype=np.float64)
        if len(covariate_z) != len(observed):
            raise ValueError("covariate_z must match the training rows")
    model = pm.Model(coords={"player": player_ids})
    with model:
        if fixed_beta:
            beta = pm.Deterministic("beta", pm.math.constant(BETA_MU))
        else:
            beta = pm.Normal("beta", mu=BETA_MU, sigma=BETA_SIGMA)
        tau = pm.HalfNormal("tau", sigma=TAU_SCALE)
        sigma = pm.HalfNormal("sigma", sigma=SIGMA_SCALE)
        alpha_raw = pm.Normal("alpha_raw", mu=0.0, sigma=1.0, dims="player")
        if orthogonal:
            if player_level is None:
                raise ValueError("an orthogonal intercept needs a player level")
            level = np.asarray(player_level, dtype=np.float64)
            if level.shape != (len(player_ids),):
                raise ValueError("player_level must have one value per player")
            centered = level - float(level.mean())
            variance = float(centered @ centered)
            if variance <= 0.0:
                raise ValueError("player levels do not vary")
            slope = pm.math.dot(centered, alpha_raw) / variance
            alpha_unit = alpha_raw - slope * centered
        else:
            alpha_unit = alpha_raw
        alpha = pm.Deterministic("alpha", tau * alpha_unit, dims="player")
        mu = beta * xgb_mean + alpha[player_code]
        if censored:
            pm.Censored(
                "y",
                pm.Normal.dist(mu=mu, sigma=sigma),
                lower=0.0,
                observed=observed,
            )
        else:
            gamma = pm.Normal("gamma", mu=0.0, sigma=GAMMA_SIGMA)
            width = sigma * pm.math.exp(gamma * covariate_z)
            pm.Normal("y", mu=mu, sigma=width, observed=observed)
    return model


def sample_points(
    *,
    player_ids: list[int],
    player_code: Any,
    xgb_mean: Any,
    observed: Any,
    covariate_z: Any,
    draws: int,
    tune: int,
    chains: int,
    seed: int,
    censored: bool = False,
    orthogonal: bool = False,
    player_level: Any = None,
    fixed_beta: bool = False,
) -> Any:
    """NUTS on the training rows of one player subset. Holdout rows stay out."""
    model = points_model(
        player_ids=player_ids,
        player_code=player_code,
        xgb_mean=xgb_mean,
        observed=observed,
        covariate_z=covariate_z,
        censored=censored,
        orthogonal=orthogonal,
        player_level=player_level,
        fixed_beta=fixed_beta,
    )
    with model:
        return pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            cores=1,
            random_seed=seed,
            progressbar=False,
            target_accept=TARGET_ACCEPT,
        )


def draws_from(idata: Any, player_ids: list[int]) -> list[PosteriorDraw]:
    """Stack every chain into one draw list.

    ``player_ids`` has to equal the posterior ``player`` coordinate, in that
    order. A swapped list would attach each intercept to the wrong player.
    """
    coord = [int(value) for value in idata.posterior.coords["player"].values]
    if coord != list(player_ids):
        raise ValueError("player_ids are not the posterior player coordinate, in that order")
    beta = np.asarray(idata.posterior["beta"].values, dtype=np.float64).reshape(-1)
    sigma = np.asarray(idata.posterior["sigma"].values, dtype=np.float64).reshape(-1)
    if "gamma" in idata.posterior:
        gamma = np.asarray(idata.posterior["gamma"].values, dtype=np.float64).reshape(-1)
    else:
        gamma = np.zeros(len(beta), dtype=np.float64)
    alpha = np.asarray(idata.posterior["alpha"].values, dtype=np.float64)
    alpha = alpha.reshape(-1, alpha.shape[-1])
    if alpha.shape[1] != len(player_ids):
        raise ValueError("alpha columns do not match player_ids")
    if not (len(beta) == len(sigma) == len(alpha) == len(gamma)):
        raise ValueError("posterior arrays have different draw counts")
    draws: list[PosteriorDraw] = []
    for index in range(len(beta)):
        draws.append(
            PosteriorDraw(
                beta=float(beta[index]),
                sigma=float(sigma[index]),
                alpha={
                    player_id: float(alpha[index, column])
                    for column, player_id in enumerate(player_ids)
                },
                gamma=float(gamma[index]),
            )
        )
    return draws


def parameter_rows(idata: Any, *, fixed_beta: bool = False) -> list[tuple[str, float, float]]:
    """R-hat and bulk ESS for the population parameters that move.

    A fixed ``beta`` is not gated. The report still reads the constant from
    the posterior draws.
    """
    import arviz as az

    names = ["sigma", "tau"]
    if not fixed_beta:
        names = ["beta", *names]
    if "gamma" in idata.posterior:
        names.append("gamma")
    summary: Any = az.summary(idata, var_names=names, round_to="none")
    rows: list[tuple[str, float, float]] = []
    for name in names:
        rows.append((name, float(summary.loc[name, "r_hat"]), float(summary.loc[name, "ess_bulk"])))
    return rows


def divergence_count(idata: Any) -> int:
    diverging = np.asarray(idata.sample_stats["diverging"].values)
    return int(diverging.sum())
