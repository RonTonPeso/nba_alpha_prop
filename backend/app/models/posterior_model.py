"""Sample the points model.

This is the starting likelihood from ``docs/provenance/m6-plan.md``.
The agent typed it for the M6 diagnostic. It is not a settled model and
it is not an ADR. Ronnie replaces the priors before an acceptance fit.
The parameter names ``beta``, ``sigma``, and ``tau`` are what the gate reads.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pymc as pm

from app.models.posterior import BETA_MU, BETA_SIGMA, SIGMA_SCALE, TAU_SCALE, PosteriorDraw

TARGET_ACCEPT = 0.9


def sample_points(
    *,
    player_ids: list[int],
    player_code: Any,
    xgb_mean: Any,
    observed: Any,
    draws: int,
    tune: int,
    chains: int,
    seed: int,
) -> Any:
    """NUTS on the training rows of one player subset. Holdout rows stay out."""
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("player_ids must be unique")
    if not (len(player_code) == len(xgb_mean) == len(observed)):
        raise ValueError("training columns must be the same length")
    with pm.Model(coords={"player": player_ids}):
        beta = pm.Normal("beta", mu=BETA_MU, sigma=BETA_SIGMA)
        tau = pm.HalfNormal("tau", sigma=TAU_SCALE)
        sigma = pm.HalfNormal("sigma", sigma=SIGMA_SCALE)
        alpha = pm.Normal("alpha", mu=0.0, sigma=tau, dims="player")
        mu = beta * xgb_mean + alpha[player_code]
        pm.Normal("y", mu=mu, sigma=sigma, observed=observed)
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
    alpha = np.asarray(idata.posterior["alpha"].values, dtype=np.float64)
    alpha = alpha.reshape(-1, alpha.shape[-1])
    if alpha.shape[1] != len(player_ids):
        raise ValueError("alpha columns do not match player_ids")
    if not (len(beta) == len(sigma) == len(alpha)):
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
            )
        )
    return draws


def parameter_rows(idata: Any) -> list[tuple[str, float, float]]:
    """R-hat and bulk ESS for the three population parameters."""
    import arviz as az

    summary: Any = az.summary(idata, var_names=["beta", "sigma", "tau"], round_to="none")
    rows: list[tuple[str, float, float]] = []
    for name in ("beta", "sigma", "tau"):
        rows.append((name, float(summary.loc[name, "r_hat"]), float(summary.loc[name, "ess_bulk"])))
    return rows


def divergence_count(idata: Any) -> int:
    diverging = np.asarray(idata.sample_stats["diverging"].values)
    return int(diverging.sum())
