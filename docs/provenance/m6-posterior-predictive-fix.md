# Provenance: M6 stored posterior predictive fix

## Milestone / acceptance aimed at

Retrospective review `docs/reviewer-m5-m7-m8.md`, M6 **B1**:

> Stored rows hold the posterior of the mean, not the posterior
> predictive. … For points the stored std is 0.48 when it should be about
> 6.7. … M8 computes probabilities from the stored rows.

Also ADR-4's claim that the stored row is a posterior predictive summary.

## Choice

Sample one observation per posterior draw when writing (and when
summarizing MAE):

`y ~ N(mu, sigma * exp(gamma * z))`, then stop at 0 if censored.

`mu` remains `beta * xgb_mean + alpha`. Brier scoring already used
`tail_probability` with `sigma`; only the stored mean/std/quantiles and
the MAE summary were wrong.

Rejected: bumping to `pymc-m6-v2` and leaving the bad rows in place. The
dashboard prefers `pymc-m6-v1`. Rewriting summaries in place with
`--rewrite-stored` keeps the version string and clears the spike
densities without a preference change.

Rejected: analytical `sqrt(E[sigma^2] + Var(mu))` only. Sampling matches
the existing PPC path (`_ppc_means`) and the censored clip.

## What would make this wrong

- Stored std still ~0.5 after rewrite (query below would show it).
- Dashboard model P still collapses to 0/1 on mid-range lines.
- A test that only checks `predictive_summary` on hand-typed arrays would
  miss a regression that stops passing `sigma` into `_predictive_draws`.

## Verified

- `uv run pytest tests/test_posterior.py` → 26 passed (includes
  `test_predictive_draws_include_observation_noise`).
- Rewrite from acceptance traces with `--rewrite-stored`:

  ```bash
  # points (orthogonal), rebounds (orthogonal), assists (fixed-beta)
  uv run python -m app.models.posterior_fit --prop … --censored --oof \
    --population [--orthogonal|--fixed-beta] --draws 2000 --tune 1000 \
    --chains 4 --from-trace models/m6-…-acceptance.nc --rewrite-stored
  ```

- Avg stored `std` after rewrite: points 6.485 (was 0.483), rebounds
  2.689 (was 0.194), assists 2.129 (was 0.188). Counts unchanged
  (1798 / 1328 / 1066).
- Today slate `2026-06-03`: extreme model P (<2% or >98%) fell from 98/108
  in the review to 8/100 on a live API read. Towns points 14.5 → model P
  ≈ 0.50, std ≈ 6.58 (was a spike).
- Report Briers unchanged (still scored from the trace): points 0.157591,
  rebounds 0.167559, assists 0.147770.

## What changed after review

Review: `docs/reviewer-m5-m7-m8.md` (M6 B1).

- Required: store posterior predictive including observation noise; stop
  feeding mean-only std to M8.
- Code: `_predictive_draws` replaces `_latent_draws`; `_store_posterior`
  and `_point_mae` take `sigma`/`gamma`; `--rewrite-stored` updates
  existing rows; ADR-4 wording clarified; regression test added.
- Left for later: M6 Important items (width share of Brier gain, holdout
  variant search, docstring ownership). Those do not unblock the
  dashboard.
