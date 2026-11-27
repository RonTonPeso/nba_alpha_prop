# Review M6 diagnostic

Fresh session. Do not write fix code. Findings only.

The work is uncommitted on local `m5-xgb`. `origin/main` has M5 and does not have this diff. Review the working tree.

## What this claims

A points posterior around the M5 booster, sampled for 40 players. It is a diagnostic. The milestone stays open.

Command: `uv run python -m app.models.posterior_fit`

Report: `docs/results/m6-diagnostic.md`

- Holdout starts 2025-12-05. Booster trained on all 86,759 training rows. Sampler sees 5,006 rows from 40 players.
- Residual width 6.002. Subset Brier 0.163713 vs residual band 0.163925 on 581 contracts.
- Divergences 0. `tau` R-hat 1.090, bulk ESS 28. Gate failed.
- No `pymc-m6-v1` rows written.
- `uv run pytest -q` reported 110 passed. `uv run mypy app tests` was clean. The sampler is not in the unit tests.

Spec: `docs/Roadmap.md` M6 and `docs/provenance/m6-plan.md`. The bar for a real pass is residual Brier 0.159651 on 18,878 contracts, not this subset.

## Read these

- `backend/app/models/posterior.py`
- `backend/app/models/posterior_model.py`
- `backend/app/models/posterior_fit.py`
- `backend/tests/test_posterior.py`
- `docs/results/m6-diagnostic.md`
- `docs/provenance/m6-diagnostic.md`

## Check

1. Holdout labels never update `alpha`. The booster for a holdout row was fit only on dates before the cut.
2. The 581-contract Brier uses the same lines and the same over rule as M5 (`stat >= line`). The residual band on those contracts uses the full-training width, not a width fit on the 40.
3. The likelihood matches the plan: `beta * xgb_mean + alpha_player`, one `sigma`, `alpha` pooled to 0. Priors are the starting ones, not a tuned set.
4. R-hat and ESS are the bulk numbers for `beta`, `sigma`, and `tau` only. Say if the gate or the printed diagnostics are wrong.
5. Tests that would still pass if the sampler saw the holdout, or if `tau` did not move.

Ignore position clusters, the nightly job, and rebounds or assists. Those are out of this slice on purpose.

## Output

## Summary

## Blocking

## Important

## Suggestions

## What's done well

File and line for every finding. If a section is empty, say so.
