"""NUTS run for one prop posterior around the M5 booster.

Usage, from ``backend/``::

    uv run python -m app.models.posterior_fit --prop rebounds

The booster is refit on every training row before 2025-12-05, the same
cut and the same settings as M5. The sampler then sees a seeded subset,
40 players by default. ``--population --orthogonal --censored --oof``
is the acceptance sample for that prop. It writes ``pymc-m6-v1`` rows only
when that sample beats the residual band and the gate passes.
"""

from __future__ import annotations

import argparse
import logging
import math
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from sqlmodel import Session

from app.backtest.metrics import brier_score, probability_at_least
from app.models.baseline import PROP_TYPES
from app.models.boost import fit_regressor, predict, residual_std, shipped_mean
from app.models.compare import HOLDOUT_FRACTION, holdout_start, in_headline
from app.models.fit import Example, _lines, load_examples
from app.models.posterior import (
    DIAGNOSTIC_PLAYERS,
    DIAGNOSTIC_SEED,
    LocationTradeoff,
    covariate_scale,
    date_blocks,
    diagnostic_players,
    diagnostics_pass,
    histogram,
    location_tradeoff,
    player_index,
    ppc_svg,
    sampler_training_rows,
    standardized_covariate,
    tail_probability,
    tradeoff_note,
    tradeoff_svg,
)
from app.models.posterior_model import (
    POSTERIOR_VERSION,
    TARGET_ACCEPT,
    divergence_count,
    draws_from,
    parameter_rows,
    predictive_summary,
    sample_points,
)

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[3]
_RESULTS = _ROOT / "docs" / "results"
_OOF_FOLDS = 5
_PPC = {
    "points": (60.0, 5.0),
    "rebounds": (30.0, 2.0),
    "assists": (20.0, 2.0),
}


def _column(examples: list[Example], index: int) -> list[float]:
    return [example.actual[index] for example in examples]


def _prop_index(prop_type: str) -> int:
    if prop_type not in PROP_TYPES:
        raise ValueError(f"unsupported prop_type {prop_type!r}")
    return PROP_TYPES.index(prop_type)


def _result_stem(*, prop_type: str, acceptance: bool) -> str:
    base = "m6-posterior" if acceptance else "m6-diagnostic"
    if prop_type == "points":
        return base
    return f"{base}-{prop_type}"


def _out_of_fold_means(
    examples: list[Example],
    *,
    prop_index: int,
    folds: int = _OOF_FOLDS,
) -> dict[int, float]:
    """Shipped mean from a booster fit only on earlier date blocks.

    The earliest block has no earlier dates, so those examples are absent.
    Keys are ``id(example)`` for the same objects the caller still holds.
    """
    blocks = date_blocks([example.game_date for example in examples], folds)
    by_date: dict[date, list[Example]] = {}
    for example in examples:
        by_date.setdefault(example.game_date, []).append(example)
    found: dict[int, float] = {}
    earlier: list[Example] = []
    for block in blocks:
        block_rows = [row for day in block for row in by_date[day]]
        if earlier:
            model = fit_regressor(
                np.asarray([row.features for row in earlier], dtype=np.float64),
                np.asarray(_column(earlier, prop_index), dtype=np.float64),
            )
            predicted = predict(
                model, np.asarray([row.features for row in block_rows], dtype=np.float64)
            )
            for row, value in zip(block_rows, predicted, strict=True):
                found[id(row)] = shipped_mean(value)
        earlier.extend(block_rows)
    return found


def _ppc_means(
    *,
    xgb_mean: Any,
    player_code: Any,
    covariate_z: Any,
    beta: Any,
    sigma: Any,
    gamma: Any,
    alpha: Any,
    replicates: int,
    seed: int,
    clip_at_zero: bool = False,
    upper: float = 60.0,
    bin_width: float = 5.0,
) -> list[float]:
    """Mean histogram of normal draws from a thinned set of posterior draws."""
    rng = np.random.default_rng(seed)
    step = max(len(beta) // replicates, 1)
    chosen = list(range(0, len(beta), step))[:replicates]
    bins = len(histogram([0.0], upper=upper, width=bin_width))
    totals = np.zeros(bins, dtype=np.float64)
    for index in chosen:
        mu = beta[index] * xgb_mean + alpha[index, player_code]
        width = np.maximum(sigma[index] * np.exp(gamma[index] * covariate_z), 1e-3)
        draw = rng.normal(mu, width)
        if clip_at_zero:
            draw = np.maximum(draw, 0.0)
        counts = histogram([float(value) for value in draw], upper=upper, width=bin_width)
        totals += np.asarray(counts, dtype=np.float64)
    return [float(value / len(chosen)) for value in totals]


def render_report(
    *,
    holdout_on: str,
    player_ids: list[int],
    seed: int,
    chains: int,
    tune: int,
    draws: int,
    target_accept: float,
    train_rows: int,
    holdout_rows: int,
    residual_width: float,
    xgb_brier: float | None,
    posterior_brier: float | None,
    contracts: int,
    parameters: list[tuple[str, float, float]],
    divergences: int,
    passed: bool,
    tradeoff: LocationTradeoff,
    covariate_note: str,
    likelihood_note: str,
    trace_name: str,
    acceptance: bool = False,
    rows_written: int = 0,
    posterior_mae: float | None = None,
    residual_mae: float | None = None,
    mae_rows: int = 0,
    prop_type: str = "points",
    ppc_upper: float = 60.0,
    ppc_width: float = 5.0,
) -> str:
    def brier_text(value: float | None) -> str:
        if value is None:
            return "not scored"
        return f"{value:.6f} on {contracts} contracts"

    stem = _result_stem(prop_type=prop_type, acceptance=acceptance)
    other = [name for name in PROP_TYPES if name != prop_type]
    lines = [
        (
            f"# M6 {prop_type} posterior"
            if acceptance
            else f"# M6 {prop_type} posterior, diagnostic subset"
        ),
        "",
        (
            f"This is the {prop_type} acceptance sample, "
            f"{len(player_ids)} players in the likelihood."
            if acceptance
            else f"This is a seeded {len(player_ids)}-player NUTS run."
        ),
        (
            f"{other[0].capitalize()} and {other[1]} are not in this fit."
            if acceptance
            else "It is not the acceptance fit. The milestone stays open."
        ),
        "",
        (
            f"`pymc-m6-v1` rows written for the scored holdout: {rows_written}."
            if rows_written
            else "No prediction row was written."
        ),
        "`baseline-m3-v1` and `xgb-m5-v1` were not changed.",
        "",
        "The holdout booster is trained on every training date and no holdout date.",
        (
            "The sampler's training rows are the out-of-fold rows of the players in the likelihood."
            if acceptance
            else "The sampler's training rows are the subset only."
        ),
        "Holdout labels were not used to update a player intercept.",
        "The player intercept is non-centered. Alpha equals tau times a standard normal.",
        likelihood_note,
        covariate_note,
        "",
        f"Holdout starts: {holdout_on}.",
        (
            f"Subset players: {len(player_ids)}. Seed: {seed}. "
            f"Chains: {chains}. Tune: {tune}. Draws: {draws}. "
            f"Target accept: {target_accept}."
        ),
        (
            f"Players in the sampler: {len(player_ids)}."
            if len(player_ids) > 60
            else "Player ids: " + ", ".join(str(player_id) for player_id in player_ids) + "."
        ),
        f"Subset training rows: {train_rows}. Subset headline holdout rows: {holdout_rows}.",
        f"M5 residual width, fit on all training rows: {residual_width:.3f}.",
        "",
        (
            f"Brier is every headline {prop_type} contract."
            if acceptance
            else "Brier is only the headline contracts of this subset."
        ),
        (
            "The M5 figure of 0.159651 is 18878 contracts across points, rebounds, and assists."
            if acceptance
            else "A lower number on a subset does not close the milestone."
        ),
        f"Residual-band Brier: {brier_text(xgb_brier)}.",
        f"Posterior Brier: {brier_text(posterior_brier)}.",
        (
            f"{prop_type.capitalize()} MAE, XGBoost clipped mean: "
            f"{residual_mae:.3f} on {mae_rows} player-props."
            if residual_mae is not None
            else f"{prop_type.capitalize()} MAE, XGBoost clipped mean: not scored."
        ),
        (
            f"{prop_type.capitalize()} MAE, posterior predictive mean: "
            f"{posterior_mae:.3f} on {mae_rows} player-props."
            if posterior_mae is not None
            else f"{prop_type.capitalize()} MAE, posterior predictive mean: not scored."
        ),
        "",
        f"Divergences: {divergences}.",
        "Population parameters, unrounded, printed to 4 decimals:",
    ]
    for name, rhat, ess in parameters:
        lines.append(f"- `{name}` R-hat {rhat:.4f}, bulk ESS {ess:.1f}.")
    lines.append(
        "The gate reads the unrounded R-hat and ESS. "
        "A non-finite value fails. Zero divergences are required."
    )
    if passed:
        lines.append(
            "The gate passed." if acceptance else "The diagnostic gate passed for this subset."
        )
    else:
        lines.append("The diagnostic gate did not pass.")
    lines.extend(
        [
            "",
            f"![Posterior predictive check]({stem}.svg)",
            "",
            f"Blue bars are observed {prop_type}. Amber bars are the mean "
            "posterior predictive count.",
            "The first bin is every value below 0. The last bin is every value "
            f"at or above {ppc_upper:.0f}.",
            f"The bins between them are {ppc_width:.0f} wide.",
            "",
            f"![Beta against tau]({stem}-tradeoff.svg)",
            "",
            (
                "Correlation of beta and tau: not defined."
                if not math.isfinite(tradeoff.beta_tau_correlation)
                else f"Correlation of beta and tau: {tradeoff.beta_tau_correlation:.3f}."
            ),
            f"Mean beta: {tradeoff.mean_beta:.3f}.",
            (
                "Mean slope of the player intercepts on the player's mean "
                f"booster prediction: {tradeoff.mean_slope:.3f}."
            ),
            (
                "Correlation of beta with that slope: not defined."
                if not math.isfinite(tradeoff.beta_slope_correlation)
                else "Correlation of beta with that slope: "
                f"{tradeoff.beta_slope_correlation:.3f}."
            ),
            tradeoff_note(tradeoff),
            f"The trace is `models/{trace_name}`. That file is gitignored.",
            "Earlier traces under `models/` are left in place.",
            "",
        ]
    )
    return "\n".join(lines)


def _predictive_draws(
    center: float,
    *,
    beta: Any,
    alpha: Any,
    sigma: Any,
    gamma: Any,
    slot: int | None,
    covariate_z: float,
    rng: np.random.Generator,
) -> Any:
    """One observation draw per posterior sample: y ~ N(mu, width).

    ``mu`` is ``beta * center + alpha``. ``width`` is
    ``sigma * exp(gamma * z)``. This is the posterior predictive the
    dashboard and stored rows need. The location alone is not.
    """
    mu = beta * center
    if slot is not None:
        mu = mu + alpha[:, slot]
    width = np.maximum(sigma * np.exp(gamma * covariate_z), 1e-3)
    return rng.normal(mu, width)


def _point_mae(
    examples: list[Example],
    *,
    prop_index: int,
    hold_mean: dict[int, float],
    beta: Any,
    alpha: Any,
    sigma: Any,
    gamma: Any,
    ordered_ids: list[int],
    clip_at_zero: bool,
    z_center: float,
    z_scale: float,
    seed: int,
) -> tuple[float | None, float | None]:
    """MAE of the predictive mean and of the clipped booster mean."""
    if not examples:
        return None, None
    index = {player_id: slot for slot, player_id in enumerate(ordered_ids)}
    rng = np.random.default_rng(seed)
    posterior_error = 0.0
    residual_error = 0.0
    for example in examples:
        center = hold_mean[id(example)]
        summary = predictive_summary(
            _predictive_draws(
                center,
                beta=beta,
                alpha=alpha,
                sigma=sigma,
                gamma=gamma,
                slot=index.get(example.player_id),
                covariate_z=standardized_covariate(center, center=z_center, scale=z_scale),
                rng=rng,
            ),
            clip_at_zero=clip_at_zero,
        )
        actual = float(example.actual[prop_index])
        posterior_error += abs(summary[0] - actual)
        residual_error += abs(center - actual)
    count = len(examples)
    return posterior_error / count, residual_error / count


def _store_posterior(
    session: Session,
    *,
    prop_type: str,
    examples: list[Example],
    hold_mean: dict[int, float],
    beta: Any,
    alpha: Any,
    sigma: Any,
    gamma: Any,
    ordered_ids: list[int],
    clip_at_zero: bool,
    orthogonal: bool,
    z_center: float,
    z_scale: float,
    seed: int,
    replace: bool = False,
) -> int:
    """Write one row per scored holdout player-game.

    Existing rows stay unless ``replace`` is true, in which case mean/std
    and quantiles are rewritten in place (used to fix mean-only rows).
    """
    from sqlmodel import select

    from app.db.tables import Prediction
    from app.models.fit import _existing
    from app.models.predict import prediction_time_for

    existing = _existing(session, POSTERIOR_VERSION)
    index = {player_id: slot for slot, player_id in enumerate(ordered_ids)}
    rng = np.random.default_rng(seed)
    written = 0
    for example in examples:
        ident = (example.player_id, example.game_id, prop_type)
        center = hold_mean[id(example)]
        mean, std, low, mid, high = predictive_summary(
            _predictive_draws(
                center,
                beta=beta,
                alpha=alpha,
                sigma=sigma,
                gamma=gamma,
                slot=index.get(example.player_id),
                covariate_z=standardized_covariate(center, center=z_center, scale=z_scale),
                rng=rng,
            ),
            clip_at_zero=clip_at_zero,
        )
        payload = {
            "distribution": "posterior",
            "censored_at_zero": clip_at_zero,
            "orthogonal_intercept": orthogonal,
            "predictive": "observation",
        }
        if ident in existing:
            if not replace:
                continue
            row = session.exec(
                select(Prediction).where(
                    Prediction.player_id == example.player_id,
                    Prediction.game_id == example.game_id,
                    Prediction.prop_type == prop_type,
                    Prediction.model_version == POSTERIOR_VERSION,
                )
            ).one()
            row.mean = mean
            row.std = std
            row.quantile_10 = low
            row.quantile_50 = mid
            row.quantile_90 = high
            row.n_games = example.n_games
            row.low_confidence = not in_headline(example.rest_days)
            row.payload = payload
            session.add(row)
        else:
            session.add(
                Prediction(
                    player_id=example.player_id,
                    game_id=example.game_id,
                    prop_type=prop_type,
                    model_version=POSTERIOR_VERSION,
                    prediction_time=prediction_time_for(example.game_date),
                    mean=mean,
                    std=std,
                    quantile_10=low,
                    quantile_50=mid,
                    quantile_90=high,
                    n_games=example.n_games,
                    low_confidence=not in_headline(example.rest_days),
                    payload=payload,
                )
            )
        written += 1
    if written:
        session.commit()
    return written


def run(
    session: Session,
    *,
    prop_type: str = "points",
    players: int = DIAGNOSTIC_PLAYERS,
    draws: int = 400,
    tune: int = 400,
    chains: int = 4,
    seed: int = DIAGNOSTIC_SEED,
    out_of_fold: bool = False,
    censored: bool = False,
    population: bool = False,
    orthogonal: bool = False,
    fixed_beta: bool = False,
    trace_in: Path | None = None,
    rewrite_stored: bool = False,
) -> tuple[str, str, str]:
    """Return the report text, the predictive SVG, and the beta-tau SVG.

    Writes a gitignored trace. Writes ``pymc-m6-v1`` rows only when the
    acceptance bar clears. Earlier traces are left in place.
    ``rewrite_stored`` updates existing rows' predictive summaries in place.
    """
    prop_index = _prop_index(prop_type)
    ppc_upper, ppc_width = _PPC[prop_type]
    examples = load_examples(session)
    if not examples:
        raise RuntimeError("no feature rows were built")
    start = holdout_start((example.game_date for example in examples), HOLDOUT_FRACTION)
    train = [example for example in examples if example.game_date < start]
    holdout = [example for example in examples if example.game_date >= start]
    if not train or not holdout:
        raise RuntimeError("the date cut left one side empty")
    logger.info(
        "prop %s train %d holdout %d from %s",
        prop_type,
        len(train),
        len(holdout),
        start.isoformat(),
    )

    train_x = np.asarray([example.features for example in train], dtype=np.float64)
    model = fit_regressor(train_x, np.asarray(_column(train, prop_index), dtype=np.float64))
    train_pred = predict(model, train_x)
    width = residual_std(_column(train, prop_index), train_pred)
    train_mean = {
        id(example): shipped_mean(value) for example, value in zip(train, train_pred, strict=True)
    }
    hold_pred = predict(
        model, np.asarray([example.features for example in holdout], dtype=np.float64)
    )
    hold_mean = {
        id(example): shipped_mean(value) for example, value in zip(holdout, hold_pred, strict=True)
    }

    headline_holdout = [example for example in holdout if in_headline(example.rest_days)]
    if population:
        chosen = sorted({example.player_id for example in train})
    else:
        chosen = diagnostic_players(
            [example.player_id for example in train],
            [example.player_id for example in headline_holdout],
            n=players,
            seed=seed,
        )
    if len(chosen) < 2:
        raise RuntimeError("the diagnostic subset needs at least two players")
    chosen_set = set(chosen)
    sub_train = list(sampler_training_rows(examples, holdout_on=start, player_ids=chosen))
    if population:
        sub_hold = list(headline_holdout)
    else:
        sub_hold = [example for example in headline_holdout if example.player_id in chosen_set]
    if out_of_fold:
        fold_means = _out_of_fold_means(train, prop_index=prop_index)
        before = len(sub_train)
        sub_train = [example for example in sub_train if id(example) in fold_means]
        covariate = fold_means
        covariate_note = (
            f"The sampler's booster prediction comes from {_OOF_FOLDS} expanding date blocks "
            "inside the training period. Each block is predicted by a booster fit "
            "only on earlier blocks. The earliest block is left out. "
            f"Subset training rows with a prediction: {len(sub_train)} of {before}. "
            "Holdout rows use the booster trained on every training date."
        )
        trace_name = f"m6-{prop_type}-oof.nc"
    else:
        covariate = train_mean
        covariate_note = (
            "On a training row the sampler sees the booster's prediction of that same row."
        )
        trace_name = f"m6-{prop_type}-variance.nc"
    if censored:
        likelihood_note = (
            "The likelihood is a normal left-censored at 0. A positive observation "
            "uses the normal density. A zero uses the probability of the latent "
            "normal falling at or below 0. The width is the shared sigma. "
            "The priors on beta, tau, and sigma are unchanged. "
            "For a line above 0, the scored probability is the latent upper tail."
        )
        if population and out_of_fold:
            trace_name = f"m6-{prop_type}-acceptance.nc"
        else:
            trace_name = (
                f"m6-{prop_type}-censored-oof.nc" if out_of_fold else f"m6-{prop_type}-censored.nc"
            )
    else:
        likelihood_note = (
            "The row width is sigma times exp(gamma times z). "
            "z is the booster mean standardized on the sampler's training rows. "
            "A gamma of 0 is the shared width. "
            "The priors on beta, tau, and sigma are unchanged."
        )
    if orthogonal:
        likelihood_note += (
            " The player intercept is the part of the non-centered draw with no slope "
            "on that player's mean booster prediction. That slope is zero in every draw, "
            "so a correlation of beta with it is not a finding."
        )
        if population:
            trace_name = f"m6-{prop_type}-orthogonal-acceptance.nc"
        elif out_of_fold:
            trace_name = f"m6-{prop_type}-orthogonal-oof.nc"
        else:
            trace_name = f"m6-{prop_type}-orthogonal.nc"
    if fixed_beta:
        likelihood_note += (
            " Beta is fixed at 1. The booster mean is the location scale, "
            "and the player intercept is the only free location hierarchy."
        )
        if population:
            trace_name = f"m6-{prop_type}-fixedbeta-acceptance.nc"
        elif out_of_fold:
            trace_name = f"m6-{prop_type}-fixedbeta-oof.nc"
        else:
            trace_name = f"m6-{prop_type}-fixedbeta.nc"
    if len(sub_train) < 2:
        raise RuntimeError("the sampler has fewer than two training rows")
    logger.info(
        "subset players %d fit players %d train rows %d holdout rows %d",
        len(chosen),
        len({example.player_id for example in sub_train}),
        len(sub_train),
        len(sub_hold),
    )

    fit_ids = sorted({example.player_id for example in sub_train})
    codes = player_index(fit_ids)
    ordered_ids = [
        player_id for player_id, _index in sorted(codes.items(), key=lambda item: item[1])
    ]
    code = np.asarray([codes[example.player_id] for example in sub_train], dtype=np.int64)
    xgb_train = np.asarray([covariate[id(example)] for example in sub_train], dtype=np.float64)
    observed = np.asarray(_column(sub_train, prop_index), dtype=np.float64)
    z_center, z_scale = covariate_scale([float(value) for value in xgb_train])
    z_train = np.asarray(
        [
            standardized_covariate(float(value), center=z_center, scale=z_scale)
            for value in xgb_train
        ],
        dtype=np.float64,
    )
    logger.info("covariate center %.3f scale %.3f", z_center, z_scale)
    player_level = [float(xgb_train[code == index].mean()) for index in range(len(ordered_ids))]
    if trace_in is None:
        idata = sample_points(
            player_ids=ordered_ids,
            player_code=code,
            xgb_mean=xgb_train,
            observed=observed,
            covariate_z=z_train,
            draws=draws,
            tune=tune,
            chains=chains,
            seed=seed,
            censored=censored,
            orthogonal=orthogonal,
            player_level=player_level if orthogonal else None,
            fixed_beta=fixed_beta,
        )
    else:
        import arviz as az

        loaded: Any = az.from_netcdf(trace_in)  # type: ignore[no-untyped-call]
        idata = loaded
        chains = int(idata.posterior.sizes["chain"])
        draws = int(idata.posterior.sizes["draw"])
    parameters = parameter_rows(idata, fixed_beta=fixed_beta)
    divergences = divergence_count(idata)
    draws_list = draws_from(idata, ordered_ids)
    logger.info("draws %d divergences %d", len(draws_list), divergences)

    lines = _lines(session)
    posterior_pairs: list[tuple[float, int]] = []
    residual_pairs: list[tuple[float, int]] = []
    for example in sub_hold:
        for line in lines.get((example.player_id, example.game_id, prop_type), []):
            outcome = 1 if example.actual[prop_index] >= line else 0
            posterior_pairs.append(
                (
                    tail_probability(
                        draws_list,
                        player_id=example.player_id,
                        xgb_mean=hold_mean[id(example)],
                        line=line,
                        covariate_z=standardized_covariate(
                            hold_mean[id(example)],
                            center=z_center,
                            scale=z_scale,
                        ),
                        censored_at_zero=censored,
                    ),
                    outcome,
                )
            )
            residual_pairs.append(
                (probability_at_least(hold_mean[id(example)], width, line), outcome)
            )
    posterior_brier = brier_score(posterior_pairs) if posterior_pairs else None
    residual_brier = brier_score(residual_pairs) if residual_pairs else None
    scored_holdout = [
        example
        for example in sub_hold
        if lines.get((example.player_id, example.game_id, prop_type))
    ]

    beta = np.asarray(idata.posterior["beta"].values, dtype=np.float64).reshape(-1)
    tau = np.asarray(idata.posterior["tau"].values, dtype=np.float64).reshape(-1)
    sigma = np.asarray(idata.posterior["sigma"].values, dtype=np.float64).reshape(-1)
    if "gamma" in idata.posterior:
        gamma = np.asarray(idata.posterior["gamma"].values, dtype=np.float64).reshape(-1)
    else:
        gamma = np.zeros(len(beta), dtype=np.float64)
    alpha = np.asarray(idata.posterior["alpha"].values, dtype=np.float64)
    alpha = alpha.reshape(-1, alpha.shape[-1])
    player_mean = [float(xgb_train[code == index].mean()) for index in range(len(ordered_ids))]
    tradeoff = location_tradeoff(beta.tolist(), tau.tolist(), alpha.tolist(), player_mean)
    scatter = tradeoff_svg(beta.tolist(), tau.tolist())
    observed_counts = histogram(list(observed), upper=ppc_upper, width=ppc_width)
    predictive = _ppc_means(
        xgb_mean=xgb_train,
        player_code=code,
        covariate_z=z_train,
        beta=beta,
        sigma=sigma,
        gamma=gamma,
        alpha=alpha,
        replicates=20,
        seed=seed,
        clip_at_zero=censored,
        upper=ppc_upper,
        bin_width=ppc_width,
    )
    svg = ppc_svg(observed_counts, predictive, upper=ppc_upper)
    passed = diagnostics_pass(parameters, divergences=divergences)
    absorbed = math.isfinite(tradeoff.beta_slope_correlation) and (
        tradeoff.beta_slope_correlation <= -0.8
    )
    posterior_mae, residual_mae = _point_mae(
        sub_hold,
        prop_index=prop_index,
        hold_mean=hold_mean,
        beta=beta,
        alpha=alpha,
        sigma=sigma,
        gamma=gamma,
        ordered_ids=ordered_ids,
        clip_at_zero=censored,
        z_center=z_center,
        z_scale=z_scale,
        seed=seed,
    )
    rows_written = 0
    if (
        population
        and censored
        and out_of_fold
        and passed
        and not absorbed
        and posterior_brier is not None
        and residual_brier is not None
        and posterior_brier < residual_brier
    ):
        rows_written = _store_posterior(
            session,
            prop_type=prop_type,
            examples=scored_holdout,
            hold_mean=hold_mean,
            beta=beta,
            alpha=alpha,
            sigma=sigma,
            gamma=gamma,
            ordered_ids=ordered_ids,
            clip_at_zero=True,
            orthogonal=orthogonal,
            z_center=z_center,
            z_scale=z_scale,
            seed=seed,
            replace=rewrite_stored,
        )
    report = render_report(
        holdout_on=start.isoformat(),
        player_ids=fit_ids,
        seed=seed,
        chains=chains,
        tune=tune,
        draws=draws,
        target_accept=TARGET_ACCEPT,
        train_rows=len(sub_train),
        holdout_rows=len(sub_hold),
        residual_width=width,
        xgb_brier=residual_brier,
        posterior_brier=posterior_brier,
        contracts=len(posterior_pairs),
        parameters=parameters,
        divergences=divergences,
        passed=passed,
        tradeoff=tradeoff,
        covariate_note=covariate_note,
        likelihood_note=likelihood_note,
        trace_name=trace_name,
        acceptance=population,
        rows_written=rows_written,
        posterior_mae=posterior_mae,
        residual_mae=residual_mae,
        mae_rows=len(sub_hold),
        prop_type=prop_type,
        ppc_upper=ppc_upper,
        ppc_width=ppc_width,
    )
    trace_path = _ROOT / "models" / trace_name
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    if trace_in is None or trace_in.resolve() != trace_path.resolve():
        idata.to_netcdf(trace_path)
    return report, svg, scatter


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="NUTS run for one prop posterior.")
    parser.add_argument(
        "--prop",
        choices=list(PROP_TYPES),
        default="points",
        help="Counting stat to fit. Default points.",
    )
    parser.add_argument("--players", type=int, default=DIAGNOSTIC_PLAYERS)
    parser.add_argument("--draws", type=int, default=400)
    parser.add_argument("--tune", type=int, default=400)
    parser.add_argument("--chains", type=int, default=4)
    parser.add_argument("--seed", type=int, default=DIAGNOSTIC_SEED)
    parser.add_argument(
        "--oof",
        action="store_true",
        help="Sampler covariate is an expanding date-block booster, not the in-sample fit.",
    )
    parser.add_argument(
        "--censored",
        action="store_true",
        help="Normal likelihood left-censored at 0, with a shared width.",
    )
    parser.add_argument(
        "--population",
        action="store_true",
        help="Every training player. Requires --censored and --oof.",
    )
    parser.add_argument(
        "--orthogonal",
        action="store_true",
        help="Player intercept has no slope on the player's mean booster prediction.",
    )
    parser.add_argument(
        "--fixed-beta",
        action="store_true",
        help="Hold beta at 1. The booster mean is the location scale.",
    )
    parser.add_argument(
        "--from-trace",
        type=Path,
        default=None,
        help="Score and, when the bar clears, store rows from this NetCDF. Does not resample.",
    )
    parser.add_argument(
        "--rewrite-stored",
        action="store_true",
        help=(
            "When writing pymc-m6-v1 rows, update existing rows' predictive "
            "summaries in place (mean/std/quantiles). Use after fixing "
            "mean-only storage."
        ),
    )
    args = parser.parse_args()
    if args.population and not (args.censored and args.oof):
        parser.error("--population runs the censored out-of-fold likelihood")
    if args.rewrite_stored and not args.population:
        parser.error("--rewrite-stored only applies to an acceptance (--population) write")
    from app.db.engine import get_engine

    with Session(get_engine()) as session:
        report, svg, scatter = run(
            session,
            prop_type=args.prop,
            players=args.players,
            draws=args.draws,
            tune=args.tune,
            chains=args.chains,
            seed=args.seed,
            out_of_fold=args.oof,
            censored=args.censored,
            population=args.population,
            orthogonal=args.orthogonal,
            fixed_beta=args.fixed_beta,
            trace_in=args.from_trace,
            rewrite_stored=args.rewrite_stored,
        )
    _RESULTS.mkdir(parents=True, exist_ok=True)
    stem = _result_stem(prop_type=args.prop, acceptance=args.population)
    (_RESULTS / f"{stem}.md").write_text(report)
    (_RESULTS / f"{stem}.svg").write_text(svg)
    (_RESULTS / f"{stem}-tradeoff.svg").write_text(scatter)
    print(report)
    print(f"wrote {_RESULTS / f'{stem}.md'}")


if __name__ == "__main__":
    main()
