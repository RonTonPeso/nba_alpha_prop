"""Diagnostic NUTS run for the points posterior. Not the M6 acceptance fit.

Usage, from ``backend/``::

    uv run python -m app.models.posterior_fit

The booster is refit on every training row before 2025-12-05, the same
cut and the same settings as M5. The sampler then sees a seeded subset,
40 players by default. No prediction row is written. The milestone stays open.
"""

from __future__ import annotations

import argparse
import logging
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
    diagnostic_players,
    diagnostics_pass,
    histogram,
    player_index,
    ppc_svg,
    sampler_training_rows,
    tail_probability,
)
from app.models.posterior_model import (
    TARGET_ACCEPT,
    divergence_count,
    draws_from,
    parameter_rows,
    sample_points,
)

logger = logging.getLogger(__name__)

_RESULTS = Path(__file__).resolve().parents[3] / "docs" / "results"
_POINTS = PROP_TYPES.index("points")


def _column(examples: list[Example], index: int) -> list[float]:
    return [example.actual[index] for example in examples]


def _ppc_means(
    *,
    xgb_mean: Any,
    player_code: Any,
    beta: Any,
    sigma: Any,
    alpha: Any,
    replicates: int,
    seed: int,
) -> list[float]:
    """Mean histogram of normal draws from a thinned set of posterior draws."""
    rng = np.random.default_rng(seed)
    step = max(len(beta) // replicates, 1)
    chosen = list(range(0, len(beta), step))[:replicates]
    bins = len(histogram([0.0]))
    totals = np.zeros(bins, dtype=np.float64)
    for index in chosen:
        mu = beta[index] * xgb_mean + alpha[index, player_code]
        draw = rng.normal(mu, np.maximum(sigma[index], 1e-3))
        counts = histogram([float(value) for value in draw])
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
) -> str:
    def brier_text(value: float | None) -> str:
        if value is None:
            return "not scored"
        return f"{value:.6f} on {contracts} contracts"

    lines = [
        "# M6 points posterior, diagnostic subset",
        "",
        f"This is a seeded {len(player_ids)}-player NUTS run.",
        "It is not the acceptance fit. The milestone stays open.",
        "",
        "No prediction row was written.",
        "`baseline-m3-v1` and `xgb-m5-v1` were not changed.",
        "",
        "The booster was refit on every training row before the holdout.",
        "On a training row the sampler sees that booster's prediction of the same row.",
        "On a holdout row the booster was trained only on earlier dates.",
        "The sampler's training rows are the subset only.",
        "Holdout labels were not used to update a player intercept.",
        "",
        f"Holdout starts: {holdout_on}.",
        (
            f"Subset players: {len(player_ids)}. Seed: {seed}. "
            f"Chains: {chains}. Tune: {tune}. Draws: {draws}. "
            f"Target accept: {target_accept}."
        ),
        "Player ids: " + ", ".join(str(player_id) for player_id in player_ids) + ".",
        f"Subset training rows: {train_rows}. Subset headline holdout rows: {holdout_rows}.",
        f"M5 residual width, fit on all training rows: {residual_width:.3f}.",
        "",
        "Brier is only the headline contracts of this subset.",
        "A lower number here does not close the milestone.",
        f"Residual-band Brier: {brier_text(xgb_brier)}.",
        f"Posterior Brier: {brier_text(posterior_brier)}.",
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
        lines.append("The diagnostic gate passed for this subset.")
    else:
        lines.append("The diagnostic gate did not pass.")
    lines.extend(
        [
            "",
            "![Posterior predictive check](m6-diagnostic.svg)",
            "",
            "Blue bars are observed points. Amber bars are the mean posterior predictive count.",
            "The first bin is every value below 0. The last bin is every value at or above 60.",
            "The bins between them are 5 points wide.",
            "",
        ]
    )
    return "\n".join(lines)


def run(
    session: Session,
    *,
    players: int = DIAGNOSTIC_PLAYERS,
    draws: int = 400,
    tune: int = 400,
    chains: int = 4,
    seed: int = DIAGNOSTIC_SEED,
) -> tuple[str, str]:
    """Return the report text and the SVG. Writes nothing to the database."""
    examples = load_examples(session)
    if not examples:
        raise RuntimeError("no feature rows were built")
    start = holdout_start((example.game_date for example in examples), HOLDOUT_FRACTION)
    train = [example for example in examples if example.game_date < start]
    holdout = [example for example in examples if example.game_date >= start]
    if not train or not holdout:
        raise RuntimeError("the date cut left one side empty")
    logger.info("train %d holdout %d from %s", len(train), len(holdout), start.isoformat())

    train_x = np.asarray([example.features for example in train], dtype=np.float64)
    model = fit_regressor(train_x, np.asarray(_column(train, _POINTS), dtype=np.float64))
    train_pred = predict(model, train_x)
    width = residual_std(_column(train, _POINTS), train_pred)
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
    sub_hold = [example for example in headline_holdout if example.player_id in chosen_set]
    logger.info(
        "subset players %d train rows %d holdout rows %d",
        len(chosen),
        len(sub_train),
        len(sub_hold),
    )

    codes = player_index(chosen)
    ordered_ids = [
        player_id for player_id, _index in sorted(codes.items(), key=lambda item: item[1])
    ]
    code = np.asarray([codes[example.player_id] for example in sub_train], dtype=np.int64)
    xgb_train = np.asarray([train_mean[id(example)] for example in sub_train], dtype=np.float64)
    observed = np.asarray(_column(sub_train, _POINTS), dtype=np.float64)
    idata = sample_points(
        player_ids=ordered_ids,
        player_code=code,
        xgb_mean=xgb_train,
        observed=observed,
        draws=draws,
        tune=tune,
        chains=chains,
        seed=seed,
    )
    parameters = parameter_rows(idata)
    divergences = divergence_count(idata)
    draws_list = draws_from(idata, ordered_ids)
    logger.info("draws %d divergences %d", len(draws_list), divergences)

    lines = _lines(session)
    posterior_pairs: list[tuple[float, int]] = []
    residual_pairs: list[tuple[float, int]] = []
    for example in sub_hold:
        for line in lines.get((example.player_id, example.game_id, "points"), []):
            outcome = 1 if example.actual[_POINTS] >= line else 0
            posterior_pairs.append(
                (
                    tail_probability(
                        draws_list,
                        player_id=example.player_id,
                        xgb_mean=hold_mean[id(example)],
                        line=line,
                    ),
                    outcome,
                )
            )
            residual_pairs.append(
                (probability_at_least(hold_mean[id(example)], width, line), outcome)
            )
    posterior_brier = brier_score(posterior_pairs) if posterior_pairs else None
    residual_brier = brier_score(residual_pairs) if residual_pairs else None

    beta = np.asarray(idata.posterior["beta"].values, dtype=np.float64).reshape(-1)
    sigma = np.asarray(idata.posterior["sigma"].values, dtype=np.float64).reshape(-1)
    alpha = np.asarray(idata.posterior["alpha"].values, dtype=np.float64)
    alpha = alpha.reshape(-1, alpha.shape[-1])
    observed_counts = histogram(list(observed))
    predictive = _ppc_means(
        xgb_mean=xgb_train,
        player_code=code,
        beta=beta,
        sigma=sigma,
        alpha=alpha,
        replicates=20,
        seed=seed,
    )
    svg = ppc_svg(observed_counts, predictive)
    report = render_report(
        holdout_on=start.isoformat(),
        player_ids=chosen,
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
        passed=diagnostics_pass(parameters, divergences=divergences),
    )
    return report, svg


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Diagnostic NUTS run for the points posterior.")
    parser.add_argument("--players", type=int, default=DIAGNOSTIC_PLAYERS)
    parser.add_argument("--draws", type=int, default=400)
    parser.add_argument("--tune", type=int, default=400)
    parser.add_argument("--chains", type=int, default=4)
    parser.add_argument("--seed", type=int, default=DIAGNOSTIC_SEED)
    args = parser.parse_args()
    from app.db.engine import get_engine

    with Session(get_engine()) as session:
        report, svg = run(
            session,
            players=args.players,
            draws=args.draws,
            tune=args.tune,
            chains=args.chains,
            seed=args.seed,
        )
    _RESULTS.mkdir(parents=True, exist_ok=True)
    (_RESULTS / "m6-diagnostic.md").write_text(report)
    (_RESULTS / "m6-diagnostic.svg").write_text(svg)
    print(report)
    print(f"wrote {_RESULTS / 'm6-diagnostic.md'}")


if __name__ == "__main__":
    main()
