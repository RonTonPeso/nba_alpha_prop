# M6 diagnostic sample

## What this is for

`docs/Roadmap.md` M6, as revised the same day, allows a seeded 40-player NUTS run as a diagnostic and withholds acceptance until the points posterior beats the M5 residual Brier on the full headline contract set. The acceptance line is: on the M5 holdout, headline rest at most 14 days, the points posterior Brier is lower than the `xgb-m5-v1` residual Brier on the same contracts, and a fit that is only the 40-player subset keeps the milestone open.

## The choice

The command refits the M5 points booster on every training row before 2025-12-05, then samples the starting likelihood on 40 players drawn with seed 0 from the players who have both a training row and a headline holdout row. Two chains, 400 tune iterations, 400 draws, one core. The report is `docs/results/m6-diagnostic.md`. No `pymc-m6-v1` row is inserted.

Rejected: storing the subset posterior as `pymc-m6-v1`. Those rows would look like the acceptance model. The table still has only `baseline-m3-v1` and `xgb-m5-v1`.

Rejected: running NUTS on every training player in this pass. The plan says the 40-player run comes first, and this one already missed the diagnostic gate.

## What the command did

From `backend/`, `uv run python -m app.models.posterior_fit` on 9 Nov 2026. Copied from that run:

- Train rows 86,759, holdout rows 21,184, holdout starts 2025-12-05.
- Subset training rows 5,006. Subset headline holdout rows 1,655. Players 40.
- Residual width on all training rows 6.002.
- Residual-band Brier 0.163925 on 581 contracts. Posterior Brier 0.163713 on 581 contracts.
- Divergences 0.
- `beta` R-hat 1.0100, bulk ESS 233.0.
- `sigma` R-hat 1.0000, bulk ESS 412.0.
- `tau` R-hat 1.0900, bulk ESS 28.0.
- The diagnostic gate did not pass.

Before the review fixes, `uv run mypy app tests` reported no issues in 59 source files and `uv run pytest -q` reported 110 passed. After the fixes, `uv run pytest -q` reported 118 passed. The sampler itself is not in the unit tests.

## What would make this diagnostic the wrong next step

`tau` did not mix. A Brier edge of 0.0002 on 581 contracts, with that ESS, is not evidence the player intercept is identified. Fitting all players on top of a non-mixing `tau` would spend the acceptance sample on a sampler that has not moved.

A longer chain on this same subset is still the sampling change. Tightening the `tau` prior is a model change. The review below gives a reason to look at `beta` against `tau` before doing that, and the trace from this run was not saved, so that check has not been made.

## What changed after the 9 Nov 2026 review

The review is the fresh-session note pasted the same evening. It confirmed the split, the paired Brier, the likelihood, and the failed verdict of this run. It did not approve the diagnostic code for another sample.

What the review required:

- `diagnostics_pass` treated a NaN R-hat as a pass. ArviZ returns NaN when a parameter does not move.
- The gate was reading ArviZ's 2-decimal R-hat, and the report printed that as four digits.
- The posterior predictive histogram dropped values below 0 and at or above 60.
- The report hardcoded 40 players and the default seed, and it omitted chains, tune, draws, and target accept.
- The starting likelihood had no author. The module text said Ronnie could replace the priors.
- The tests still passed if `beta` and `alpha` were ignored, if `tau` was NaN, if intercept columns were swapped, or if a holdout row reached the sampler.
- The plot test named a mismatch and then passed a matched histogram.

What the code did about it:

- A non-finite R-hat or ESS fails. ESS of 400 fails. R-hat of 1.01 fails. Any divergence fails. `az.summary` is called with `round_to="none"`, and the gate uses that value.
- The histogram keeps a below-zero bin and an overflow bin. The SVG labels `<0`, `0`, the middle, `60+`, and the vertical scale.
- The report prints the player count, seed, chains, tune, draws, and target accept that the command received. The next default is 4 chains. This run's file still records 2.
- `draws_from` refuses a player-id list that is not the posterior coordinate in that order.
- `sampler_training_rows` drops any row on the holdout date. `run` calls it.
- The module docstring states that the agent typed the starting likelihood for this diagnostic. It is not an ADR.
- The tests cover those cases, including a constant `tau` whose ArviZ R-hat is NaN. `uv run pytest -q` reported 118 passed. The sampler was not rerun. `uv run mypy` on the four model modules and `tests/test_posterior.py` reported no issues.

What was left, and why:

- The training covariate is still the in-sample booster prediction. The plan specified the holdout covariate and said nothing about the training one. The residual width of 6.002 is also an in-sample residual, so the subset comparison stays matched. Replacing it with out-of-fold predictions would be a different model.
- No new NUTS run. The 9 Nov numbers stay the diagnostic result. The figure on disk still omits the outside bins.
- No `beta` against `tau` plot. That needs the trace, which was not saved.
- `pymc` stays a main dependency. The API image was not rebuilt, and the typecheck imports the sampler module.
- No test that the refit holdout means equal the stored `xgb-m5-v1` means. That check refits the booster. The 9 Nov command already matched the M5 row counts and the width 6.002.

## What was not done

The full-population NUTS fit was not run. Rebounds and assists were not sampled. The scheduler was not started. Prediction rows were not written. `docs/adr.md` was not edited, because the sampled model missed the gate and is still the starting prior rather than a settled design.
