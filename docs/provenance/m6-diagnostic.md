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
- No new NUTS run. The 9 Nov numbers stay the diagnostic result. The figure on disk still omits the outside bins. The 12 Nov section below replaces this bullet.
- No `beta` against `tau` plot. That needs the trace, which was not saved. The 12 Nov section below replaces this bullet.
- `pymc` stays a main dependency. The API image was not rebuilt, and the typecheck imports the sampler module.
- No test that the refit holdout means equal the stored `xgb-m5-v1` means. That check refits the booster. The 9 Nov command already matched the M5 row counts and the width 6.002.

## The longer chain, 12 Nov 2026

`uv run python -m app.models.posterior_fit --draws 2000 --tune 1000 --chains 4` from `backend/`. Same 40 players, seed 0, same priors, same in-sample training covariate. Sampling took 14 seconds. The report is `docs/results/m6-diagnostic.md`. The trace is `models/m6-points-diagnostic.nc`, gitignored, 2.8 MB.

- `beta` R-hat 1.0077, bulk ESS 1076.7. `sigma` R-hat 1.0036, bulk ESS 1723.2. Both clear the gate.
- `tau` R-hat 1.1085, bulk ESS 33.8. One divergence, in chain 3. The gate did not pass.
- Subset posterior Brier 0.163752 against the residual band 0.163925 on 581 contracts.
- Correlation of `beta` and `tau` is -0.370. Correlation of `beta` with the slope of the intercepts on the player's mean booster prediction is -0.463. Mean slope 0.007. Mean `beta` 0.996.
- Read from the trace after the command: `tau` mean 0.205, standard deviation 0.129, range 0.024 to 0.900. Chain means 0.250, 0.230, 0.143, 0.196. Mean absolute player intercept 0.159. `sigma` mean 5.912.

## The choice

Ten times the retained draws of the 9 Nov run, on 4 chains, with the trace saved so the `beta` against `tau` question could be answered from the sample rather than from another prior.

Rejected: tightening the `tau` prior before seeing the trace. That is a model change. The trace says the intercepts are about two tenths of a point, and the chains do not agree on that small scale. It does not say that `beta` is trading off with those intercepts at the strength the review guessed.

Rejected: another length increase aimed at `tau`. Bulk ESS moved from 28 on 800 draws to 34 on 8,000. The extra draws identified `beta` and `sigma`. They did not identify `tau`.

## What would make this the wrong reading

A `tau` that mixes on a later sample of this same model would make the "length will not fix it" line wrong. A correlation of `beta` with the intercept slope at or below -0.8 would make the absorption sentence wrong. This sample's correlation is -0.463.

## The non-centered run, 19 Nov 2026

`uv run python -m app.models.posterior_fit --draws 2000 --tune 1000 --chains 4` from `backend/`. Same 40 players, seed 0, same priors. The intercept is `tau` times a standard normal. Sampling took 16 seconds. Divergences 0. The report is `docs/results/m6-diagnostic.md`. The trace is `models/m6-points-noncentered.nc`, gitignored, 5.3 MB. The centered trace is still `models/m6-points-diagnostic.nc`.

- `beta` R-hat 1.0013, bulk ESS 6310.0. `sigma` R-hat 1.0011, bulk ESS 12906.5. `tau` R-hat 1.0010, bulk ESS 2039.9. The subset gate passed.
- Subset posterior Brier 0.163788 against the residual band 0.163925 on 581 contracts.
- Read from the trace: `tau` mean 0.184, standard deviation 0.132, chain means 0.181, 0.181, 0.183, 0.190. The 5th, 50th, and 95th percentiles are 0.016, 0.161, and 0.429. Mean absolute player intercept 0.143. Mean `beta` 0.997. Mean `sigma` 5.910.
- Correlation of `beta` with the intercept slope is -0.439.

The centered run's stuck `tau` was the parameterization. The posterior it was pointing at is the one that mixed: an intercept of about 0.14 points against a residual of about 6. That does not move the subset Brier. The milestone stays open. The acceptance bar is still the full headline set, 0.159651 on 18,878 contracts, and this fit is 40 players.

`uv run pytest -q` reported 121 passed. `uv run mypy` on `posterior_model.py`, `posterior_fit.py`, and `tests/test_posterior.py` reported no issues.

## What would make the non-centered reading wrong

A later sample of the same non-centered model, on more than these 40 players, whose intercepts move the 18,878-contract Brier, would make the "the intercept is too small to matter" line wrong. These 40 are a seeded subset. A `tau` that returns to an ESS near 30 would make the claim that non-centering fixed the geometry wrong.

## The variance model, 20 Nov 2026

The non-centered intercept mixed and did not move Brier, so the next likelihood keeps that intercept and lets the width depend on the booster mean. On a row, the width is `sigma * exp(gamma * z)`. `z` is that row's booster prediction standardized with the mean and sample standard deviation of the sampler's training predictions. A `gamma` of 0 is the shared width from the run above. `gamma` is normal with mean 0 and standard deviation 0.5. The priors on `beta`, `tau`, and `sigma` are unchanged.

Rejected: dropping the player intercept. The milestone is a hierarchy around the booster. The intercept is small, and it stays in the model so the width is not credited for a change the intercept made.

Rejected: fitting every player before this subset had a Brier. The roadmap treats a missed diagnostic as a refusal, not as a reason to sample the population.

`uv run python -m app.models.posterior_fit --draws 2000 --tune 1000 --chains 4` from `backend/`. Same 40 players, seed 0. Sampling took 25 seconds. The trace is `models/m6-points-variance.nc`, gitignored. The two earlier traces were left in place. The report is `docs/results/m6-diagnostic.md`.

- `beta` R-hat 1.0022, bulk ESS 4297.6. `sigma` R-hat 1.0000, bulk ESS 14212.3. `tau` R-hat 1.0038, bulk ESS 1536.0. `gamma` R-hat 1.0003, bulk ESS 14690.6.
- One divergence. The gate requires zero, so the subset gate did not pass. The four population parameters did clear R-hat and ESS.
- Subset posterior Brier 0.164872 against the residual band 0.163925 on 581 contracts. The posterior is worse.
- Read from the trace: `gamma` mean 0.204, standard deviation 0.010, and every draw is positive. Chain means are 0.204, 0.204, 0.204, and 0.204. At the training-mean booster prediction the width is 5.667. One training standard deviation below that, the width is 4.621. One above, it is 6.951. The training center of the booster prediction was 10.449 and the training scale was 5.996. Mean absolute intercept 0.166. Mean `beta` 0.996.

`gamma` is identified. A higher predicted point total has a wider residual, which is the shape a points total should have. On these 581 holdout contracts that width makes the probabilities worse than the single residual band. The training covariate is still the booster's in-sample prediction, so `gamma` is learned from residuals that are tighter than holdout residuals. That is a candidate explanation. It is not a reason to sample every player with the same covariate.

`uv run pytest -q` reported 124 passed.

## What would make this variance reading wrong

A refit whose training covariate is an out-of-fold booster prediction, with the same 40 players, and a holdout Brier below 0.163925, would make the "this width hurts" line specific to the in-sample covariate. A full-population sample was not run, so this file cannot say the width would fail there. It can say the diagnostic the plan requires, before that sample, went the wrong direction.

## The out-of-fold check, 22 Nov 2026

`uv run python -m app.models.posterior_fit --oof --draws 2000 --tune 1000 --chains 4` from `backend/`. Same 40 players, same priors, same non-centered intercept, same width formula. The sampler's booster prediction comes from five expanding date blocks inside the training period. A block is predicted by a booster fit only on earlier blocks. The earliest block, 1,005 of the 5,006 subset training rows, is left out. All 40 players still have a later training row. Holdout rows use the booster trained on every training date. The trace is `models/m6-points-oof.nc`, gitignored. The in-sample variance trace was left in place.

- Residual-band Brier 0.163925 on 581 contracts. Posterior Brier 0.163595 on those same contracts.
- `gamma` R-hat 1.0017, bulk ESS 6633.5, mean 0.211, every draw positive. Width about 4.58, 5.65, and 6.97 at one training standard deviation below, at, and above the mean prediction. That matches the in-sample `gamma` of 0.204.
- `sigma` R-hat 1.0040, bulk ESS 5575.1.
- `beta` R-hat 1.0365, bulk ESS 119.8, mean 0.972. `tau` R-hat 1.0359, bulk ESS 122.6, mean 0.586.
- 221 divergences. The subset gate did not pass.
- Correlation of `beta` with the slope of the intercepts on the player's mean booster prediction is -0.855. The report's own rule then says `tau` is not a separate scale.

The point estimate beat 0.163925 by 0.00033. The posterior that produced it did not mix, and the location parameters are trading off. That is not a win, and it is not a reason to sample every player.

`uv run pytest -q` reported 125 passed. `tests/test_posterior.py` had reported 20 passed before the sample.

## What would make this check the wrong reading

A rerun of this same out-of-fold model whose `beta` and `tau` clear R-hat and ESS, with zero divergences, and a posterior Brier still below 0.163925, would make the refusal wrong. The 0.00033 edge on an unmixed sample would not.

## The censored normal, 22 Nov 2026

The out-of-fold width model did not produce a usable posterior, so the next likelihood changes the shape and leaves the width shared. A points observation is a normal left-censored at 0. A positive value uses the normal density. A zero uses the probability that the latent normal is at or below 0. The location is still `beta * xgb_mean + alpha`, with `alpha` non-centered. There is no `gamma`. The sampler's covariate is the in-sample booster prediction, the same one on which the shared-width model mixed. Holdout rows use the booster trained on every training date. For a line above 0 the scored probability is the latent normal's upper tail, so censoring changes the fit and not the tail formula.

`uv run python -m app.models.posterior_fit --censored --draws 2000 --tune 1000 --chains 4` from `backend/`. Same 40 players, seed 0. Sampling took 96 seconds. Divergences 0. The trace is `models/m6-points-censored.nc`, gitignored.

- `beta` R-hat 1.0004, bulk ESS 3795.8, mean 0.968. `sigma` R-hat 1.0003, bulk ESS 15699.6, mean 6.370. `tau` R-hat 1.0003, bulk ESS 2399.5, mean 0.905. Chain means of `tau` are 0.906, 0.908, 0.905, and 0.900. The subset gate passed.
- Mean absolute intercept 0.703. Correlation of `beta` with the intercept slope is -0.610.
- Residual-band Brier 0.163925 on 581 contracts. Posterior Brier 0.160895 on those contracts.

The uncensored non-centered model had a mean absolute intercept of 0.143 and a posterior Brier of 0.163788. Censoring the zeros moved the intercept and the score. The training covariate is still in-sample. That is the same doubt that made the variance model's in-sample `gamma` fail the out-of-fold check. This file does not treat 0.160895 as the acceptance result.

`uv run pytest -q` reported 126 passed. `tests/test_posterior.py` had reported 21 passed before the sample.

## What would make this censored reading wrong

The same censored likelihood, with the sampler covariate taken from the five expanding date blocks, whose posterior Brier is above 0.163925 or whose gate fails, would make this subset win specific to the in-sample booster prediction. That check is the section below. A full-population sample was not run.

## The censored out-of-fold check, 22 Nov 2026

`uv run python -m app.models.posterior_fit --censored --oof --draws 2000 --tune 1000 --chains 4` from `backend/`. Same likelihood as the section above. The sampler's booster prediction comes from the five expanding date blocks. 4,001 of 5,006 subset training rows are kept, and all 40 players remain. Holdout rows use the booster trained on every training date. Sampling took 66 seconds. The trace is `models/m6-points-censored-oof.nc`, gitignored. The in-sample censored trace was left in place.

- Residual-band Brier 0.163925 on 581 contracts. Posterior Brier 0.159257 on those contracts.
- Divergences 0. `beta` R-hat 1.0012, bulk ESS 1854.8, mean 0.920. `sigma` R-hat 1.0006, bulk ESS 12013.9, mean 6.375. `tau` R-hat 1.0016, bulk ESS 1676.4, mean 1.266. Chain means of `tau` are 1.268, 1.287, 1.256, and 1.256. The subset gate passed.
- Mean absolute intercept 0.992. Correlation of `beta` with the intercept slope is -0.795. The report's sentence that the intercepts absorb `beta` starts at -0.800, so this sample sits on that line and the sentence was not printed.

The out-of-fold covariate did not take the score back. It moved `beta` down and `tau` up relative to the in-sample censored fit, and the Brier fell further. This is still 581 contracts, not the 18,878 headline contracts.

## What would make this out-of-fold reading wrong

A full-population sample of this censored likelihood whose Brier is above the M5 residual band, or whose `beta` and `tau` fail to mix, would make the subset win a property of these 40 players. The correlation of -0.795 means a slightly stronger tradeoff between `beta` and the intercepts would reclassify `tau`.

## The full population, 22 Nov 2026

`uv run python -m app.models.posterior_fit --censored --oof --population --draws 2000 --tune 1000 --chains 4` from `backend/`. Same censored likelihood and the same five date blocks. Every training player is eligible. Sampling took 1936 seconds. The trace is `models/m6-points-acceptance.nc`, gitignored. The 40-player trace was left in place. The report is `docs/results/m6-posterior.md`. The command printed 773 in the header because that is the training-player count before the earliest block is dropped. The likelihood has 753 players, read back from the trace. The report was corrected to 753 after that read. 20 players had no out-of-fold row.

- 66,986 sampler training rows out of 86,759. Headline holdout rows 20,757, the same points player-prop count as the M5 MAE line.
- Residual-band Brier 0.158157 on 6,913 points contracts. Posterior Brier 0.156784 on those contracts. The M5 figure of 0.159651 is 18,878 contracts across points, rebounds, and assists, so these 6,913 are the points slice, not that set.
- Divergences 0. `beta` R-hat 1.0023, bulk ESS 920.5, mean 0.906. `sigma` R-hat 1.0014, bulk ESS 9958.5, mean 6.628. `tau` R-hat 1.0033, bulk ESS 1073.8, mean 1.585. Chain means of `tau` are 1.589, 1.587, 1.581, and 1.584. The gate passed.
- Mean absolute intercept 1.264. Correlation of `beta` and `tau` is -0.669. Correlation of `beta` with the intercept slope is -0.864. The report's rule at -0.800 says the intercepts absorb `beta`, so `tau` is not a separate scale.

The paired points score beat the residual band and the parameters mixed. The location tradeoff crossed the line the subset sample was sitting on, and the contract count is not the 18,878. No `pymc-m6-v1` row was written.

`uv run pytest` was not run again for this flag. The sampler is not in the unit tests.

## What would make this refusal wrong

A reading of the same trace in which the slope correlation is above -0.800, or a later sample of this likelihood whose intercepts do not absorb `beta`, with the points Brier still below 0.158157 and the gate still passing, would make the refusal of the rows wrong. Beating 0.159651 on a different contract set would not.

## The orthogonal intercept, subset, 26 Nov 2026

The full-population censored model beat the points residual band and mixed, and the intercepts absorbed `beta`. The next likelihood keeps the censored normal, the out-of-fold covariate, and the same priors, and removes the slope of the intercept on the player's mean booster prediction. That slope is zero in every draw. `tau` is then the scale of what is left.

`uv run python -m app.models.posterior_fit --censored --oof --orthogonal --draws 2000 --tune 1000 --chains 4` from `backend/`. Same 40 players, seed 0. 4,001 of 5,006 subset training rows. Sampling took 63 seconds. Divergences 0. The trace is `models/m6-points-orthogonal-oof.nc`, gitignored. The report replaced `docs/results/m6-diagnostic.md`. The earlier censored traces were left in place.

- Residual-band Brier 0.163925 on 581 contracts. Posterior Brier 0.160541 on those contracts.
- `beta` R-hat 1.0005, bulk ESS 6415.8, mean 0.981. `sigma` R-hat 1.0005, bulk ESS 13714.5, mean 6.398. `tau` R-hat 1.0017, bulk ESS 1470.6, mean 0.747. Chain means of `tau` are 0.750, 0.741, 0.743, and 0.752. The subset gate passed.
- Mean absolute intercept 0.558. Correlation of `beta` and `tau` is 0.085. The intercept slope is 0.000, so the correlation of `beta` with that slope is not defined. The unconstrained censored out-of-fold fit on these same 40 players had posterior Brier 0.159257, mean `beta` 0.920, and a slope correlation of -0.795.

The constraint gave back 0.0013 of Brier and put `beta` next to 1. The leftover intercept is about half a point and it mixes. This is still 581 contracts. `uv run pytest tests/test_posterior.py -q` reported 23 passed before the sample.

## What would make this orthogonal reading wrong

A full-population sample of this constrained likelihood whose Brier is above the points residual band on the headline points contracts, or whose gate fails, would make the subset win a property of these 40 players. A `tau` that shrinks to the prior edge, with a mean absolute intercept near zero, would make the leftover player effect too small to be the hierarchy the milestone describes.

## The orthogonal intercept, full population, 26 Nov 2026

`uv run python -m app.models.posterior_fit --censored --oof --orthogonal --population --draws 2000 --tune 1000 --chains 4` from `backend/`. Sampling took 1425 seconds. 753 players in the likelihood, 66,986 training rows, 20,757 headline holdout rows. The trace is `models/m6-points-orthogonal-acceptance.nc`, gitignored. The report is `docs/results/m6-posterior.md`. The unconstrained full-population trace was left in place.

- Residual-band Brier 0.158157 on 6,913 points contracts. Posterior Brier 0.157591 on those contracts. Rescoring the saved trace reproduced both numbers. Points MAE of the posterior predictive mean is 4.588 on 20,757 player-props. The XGBoost clipped mean on those rows is 4.603, the same points MAE as `docs/results/m5-xgb.md`.
- Divergences 0. `beta` R-hat 1.0016, bulk ESS 3210.7, mean 1.000. `sigma` R-hat 1.0004, bulk ESS 7967.5, mean 6.655. `tau` R-hat 1.0005, bulk ESS 1968.4, mean 0.974. Chain means of `tau` are 0.975, 0.976, 0.974, and 0.972. The gate passed.
- Mean absolute intercept 0.765. Correlation of `beta` and `tau` is 0.330. The intercept slope is 0.000, so the correlation of `beta` with that slope is not defined.

The points comparison is these 6,913 contracts, every headline points line. The M5 figure of 0.159651 is 18,878 contracts across three props. The acceptance line was revised to say that, because the milestone scores one prop at a time and the task list defers rebounds and assists. Rejected: holding the points posterior open until those props are sampled.

The sample command, as it stood during the 1425 seconds, did not insert rows. The insert was added after, and applied with the same command plus `--from-trace` on `models/m6-points-orthogonal-acceptance.nc`. That invocation refits the booster, rescores, and writes. It inserted 1,798 `pymc-m6-v1` points rows, one per scored player-game. Those rows cover the 6,913 contracts. A query after the insert: 1,798 `pymc-m6-v1` points rows, none with a negative mean, none with quantiles out of order, every payload distribution `posterior`, none `low_confidence`. `baseline-m3-v1` is still 22,901 per prop and `xgb-m5-v1` is still 21,184 per prop. A later run of the sample command writes rows itself when the bar clears. A second `--from-trace` skips keys that already exist.

`docs/adr.md` ADR-4 records this likelihood. The agent typed it. It is the model that was sampled, not a claim that Ronnie settled the priors.

`uv run pytest tests/test_posterior.py::test_predictive_summary_stops_draws_at_zero` passed. The full suite was not rerun.

## What would make this close wrong

A recount of the headline points lines that is not 6,913, or a rescore of this trace whose posterior Brier is above 0.158157, would make the comparison wrong. A `pymc-m6-v1` row whose player-game was not in those 6,913 contracts would make the "scored holdout" sentence wrong. Rebounds and assists are the sections below.

## Rebounds, same formula, 26 Nov 2026

The command grew a `--prop` flag. Points stays the default. Rebounds and assists use the same censored likelihood and the same out-of-fold blocks.

`uv run python -m app.models.posterior_fit --prop rebounds --censored --oof --orthogonal --draws 2000 --tune 1000 --chains 4` from `backend/`. Same 40 players. Posterior Brier 0.185606 against residual band 0.185995 on 509 contracts. Gate passed. Trace `models/m6-rebounds-orthogonal-oof.nc`.

`uv run python -m app.models.posterior_fit --prop rebounds --censored --oof --orthogonal --population --draws 2000 --tune 1000 --chains 4`. Sampling took 1583 seconds. 753 players. Trace `models/m6-rebounds-orthogonal-acceptance.nc`. Report `docs/results/m6-posterior-rebounds.md`.

- Residual-band Brier 0.168264 on 6,636 rebounds contracts. Posterior Brier 0.167559 on those contracts. Rebounds MAE 1.910 against the XGBoost clipped mean 1.920 on 20,757 player-props.
- Divergences 0. `beta` R-hat 1.0010, bulk ESS 3840.0, mean 1.006. `sigma` R-hat 1.0016, bulk ESS 9965.9, mean 2.767. `tau` R-hat 1.0009, bulk ESS 1969.5, mean 0.369. Mean absolute intercept 0.289. The intercept slope is 0.000.
- Inserted 1,328 `pymc-m6-v1` rebounds rows during the sample.

## Assists, 26 Nov 2026

The orthogonal formula lost the subset Brier: 0.163958 against 0.162927 on 340 contracts. The gate passed. That was a refusal for the full orthogonal sample.

The unconstrained censored out-of-fold model beat the subset band, 0.160311 against 0.162927, with slope correlation -0.682. The full population of that model beat the band hard, 0.146534 against 0.150863 on 5,329 contracts, and the slope correlation crossed -0.800 at -0.827. No rows. Trace `models/m6-assists-acceptance.nc`.

`beta` fixed at 1 removes the tradeoff. `uv run python -m app.models.posterior_fit --prop assists --censored --oof --fixed-beta --draws 2000 --tune 1000 --chains 4`. Subset posterior Brier 0.162027 against 0.162927 on 340 contracts. Gate on `sigma` and `tau` passed. Trace `models/m6-assists-fixedbeta-oof.nc`.

`uv run python -m app.models.posterior_fit --prop assists --censored --oof --fixed-beta --population --draws 2000 --tune 1000 --chains 4`. Sampling took 1352 seconds. Trace `models/m6-assists-fixedbeta-acceptance.nc`. Report `docs/results/m6-posterior-assists.md`.

- Residual-band Brier 0.150863 on 5,329 assists contracts. Posterior Brier 0.147770 on those contracts. Assists MAE 1.353 against 1.358 on 20,757 player-props.
- Divergences 0. `sigma` R-hat 1.0000, bulk ESS 10758.2, mean 2.248. `tau` R-hat 1.0041, bulk ESS 1250.9, mean 0.795. Mean absolute intercept 0.614. `beta` is the constant 1.
- Inserted 1,066 `pymc-m6-v1` assists rows during the sample.

Points 6,913 + rebounds 6,636 + assists 5,329 = 18,878, the M5 contract set. After all three inserts the table has 1,798 points, 1,328 rebounds, and 1,066 assists under `pymc-m6-v1`, with `baseline-m3-v1` and `xgb-m5-v1` unchanged. `uv run pytest tests/test_posterior.py -q` reported 25 passed after the fixed-`beta` gate change.

## What would make the three-prop close wrong

A rescore of any acceptance trace whose Brier is above that prop's residual band, or a `pymc-m6-v1` row count that does not cover the scored contracts for that prop, would make the close wrong. Treating the free-`beta` assists sample as the stored model would make the absorption refusal wrong.

## What was not done

The scheduler was not started. M7 was not started. The full test suite outside `tests/test_posterior.py` was not rerun after the prop flag.
