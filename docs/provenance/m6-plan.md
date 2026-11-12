# M6 plan: a player intercept around the booster

Written 9 Nov 2026, before any PyMC code. A later diagnostic run, which does not close the milestone, is `docs/provenance/m6-diagnostic.md`. The audience is someone asking why this milestone no longer matches the original phase list.

## Where this aims

`docs/Roadmap.md` M6 acceptance, as revised the same day:

- On the M5 holdout, headline rest at most 14 days, the points posterior Brier is lower than the `xgb-m5-v1` residual Brier on the same contracts. The report states the contract count. Fewer contracts than the M5 score, or a fit that is only the 40-player subset, keeps the milestone open.
- R-hat under 1.01 and ESS above 400 for `beta`, `sigma`, and `tau`. A posterior predictive plot is in the report.
- `pymc-m6-v1` rows exist for the scored holdout, and the M5 rows are still there.
- One command reproduces the fit.
- `docs/adr.md` records the model that was sampled.

The number those lines have to beat is the one in `docs/provenance/m5-xgb.md`: residual Brier 0.159651 on 18,878 headline contracts, holdout starting 2025-12-05. The M3 baseline Brier of 0.168920 is not the bar.

`docs/CLAUDE.md` still asks for a hierarchical posterior wrapped around XGBoost, including pooling across similar players. The revision keeps the wrap and one level of pooling. It does not keep position clusters, because that similarity is not a column.

## What the original list assumed

The original phases build eight schools, then a hierarchy with no booster, then position clusters, then a nightly sampler, then a Brier comparison against "point estimates." The point estimate in the database is already a residual normal. Beating the M3 mean while losing to that band would not replace it.

The original acceptance also asks for an ADR under `docs/decisions/`. The records that exist are in `docs/adr.md`.

## Decisions

### The booster is the location. The hierarchy is one player intercept.

For a prop, the stat is modeled as normal around `beta * xgb_mean + alpha_player`, with one shared `sigma`. Each `alpha_player` is normal around 0 with scale `tau`. `beta` is normal around 1, so the prior trusts the M5 mean and can still shrink it. A player with no training rows keeps `alpha` at 0 and is predicted from the booster alone.

The holdout covariate is the booster trained only on dates before 2025-12-05. Player intercepts are learned on training labels only. Using a holdout game to update `alpha` is leakage. The M6 command refits `xgb-m5-v1` with the same settings as `docs/provenance/m5-xgb.md`, or loads a booster that was produced that way. The M5 files were not saved.

Rejected: a hierarchy that does not see the booster. M5 already beat the rolling mean on MAE and on residual Brier. A model that relearns the mean spends the milestone on a comparison that is finished.

Rejected: a second residual standard deviation, or quantile regression. Both are another placeholder width. The probability stored for a line is the average, over posterior draws, of the normal tail at that line.

### Points first. The other props wait.

The points residual width on the M5 training rows was about 6. Rebounds were about 2.5 and assists about 1.8. Points is where one shared width is most wrong. Rebounds and assists use the same formula only after points has R-hat, ESS, and a posterior predictive plot.

Rejected: three props in the first sampler. A diverging points model would be harder to see inside a joint fit, and nothing in the likelihood couples the props.

### The pool is all players. There is no position level.

`players` has a name and an id. It has no position and no role. The partial pool is the population of players in the training frame. A short sample shrinks toward zero, which means toward the booster.

Rejected: inventing a position from the box score, or from a hand-built list, so that Phase D of the original list can run. A made-up cluster would show up in an interview as a feature the table does not have.

### The 40-player run is a diagnostic. The reported fit is the M5 population.

The first NUTS run is a seeded subset of 40 players, points only. It checks that the sampler moves and that the posterior predictive cloud covers the observed points. A Brier win on that subset does not close the milestone.

The reported fit uses every player who has a legal training row under the M5 clocks, the same date cut, and headline rest of at most 14 days. ADVI is allowed while changing a prior. The Brier in the report is from NUTS. If that run cannot meet R-hat and ESS, the report says so and the milestone stays open. Adding a position level is not the remedy.

Rejected: publishing the ADVI fit. It is a different approximation, and the acceptance line is a NUTS diagnostic.

### Storage is a summary per holdout row and one trace per prop.

`pymc-m6-v1` stores the posterior predictive mean, sd, and 10/50/90, with `payload.distribution` set to `posterior`. The trace is one NetCDF per prop under `models/`. Those files are gitignored. Scoring a contract reads the trace and averages the tail. It does not read a blob of draws out of each prediction row.

`baseline-m3-v1` and `xgb-m5-v1` are not overwritten.

Rejected: a full draw vector on every prediction row. The holdout is about 21,000 player-games. Hundreds of draws per row is a JSONB dump, and the trace already has them.

Rejected: a nightly sampling job. The daily prediction path still learns tonight's game from a box score that does not exist before tip. The command is the proof.

### The model text is Ronnie's. The harness is the milestone's code.

McElreath chapters 1-4 are the original reading gate. The PyMC likelihood and the priors that get sampled are written by Ronnie and copied into `docs/adr.md`. The surrounding code builds the frame, refuses a future `available_at`, runs the sampler, writes R-hat and ESS, draws the posterior predictive check, and scores Brier against the residual band.

The starting priors, which the ADR can replace once he samples different ones: `beta` normal with mean 1 and sd 0.25, `tau` half-normal with scale 2 points, `sigma` half-normal with scale 8. Those scales are the size of a real points residual, not a flat prior.

Rejected: an agent-written hierarchical model checked in as if it were the reading. The original roadmap called that out, and the revision keeps it.

## What would make this plan wrong

- `beta` stays at 1 and the player intercepts do not move holdout Brier. The hierarchy is then a slower copy of the residual band, and the next model has to be a different likelihood, not a deeper hierarchy.
- The points posterior beats the residual Brier while the posterior predictive plot misses the observed distribution. The diagnostic bar failed even though the score moved. The milestone stays open.
- A contract set smaller than the 18,878 M5 headlines is reported as the same comparison. The count in the report is the check.

## What changed after the 9 Nov 2026 review

The review of the diagnostic, recorded in `docs/provenance/m6-diagnostic.md`, asked who typed the likelihood. The agent typed `backend/app/models/posterior_model.py` from the starting priors in this note. That file is the diagnostic harness's model, not the settled model and not an ADR. The rejection above still stands for checking an agent-written model in as the reading.

The same review noted that the sampler is fit to the booster's in-sample predictions. This plan specified the holdout covariate and not the training one. That choice is unchanged. The diagnostic report now says so.

## What was not done

No PyMC import, no sampler, no saved booster, no trace. NUTS runtime on this population was not measured. Whether the reading gate is already met was not checked. That was this note when it was written. The diagnostic that followed is `docs/provenance/m6-diagnostic.md`.
