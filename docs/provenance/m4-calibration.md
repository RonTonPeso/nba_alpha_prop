# M4 calibration: why it is built this way
Implementing the milestone. The audience is someone asking why each choice was made, including the ones that look arbitrary.

## Where the work started

`origin/main` is `3abadf1`, the merge of PR #3. That merge put the M3 baseline on main: rolling mean, `predictions`, the 16:00 UTC job, and `python -m app.backtest.run`. M4 is the next roadmap milestone. Branch `m4-calibration` starts there.

M3's "hit rate beats 50% on a held-out month" line is still not claimed. The reason is unchanged and is written in `docs/provenance/m3-baseline.md`: bulk-loaded `ingested_at` sits on the fetch day, so a 2025 replay that keeps both filters cannot see the rows. M4 does not drop that filter to produce a populated calibration curve.

M5 (XGBoost) and M6 (PyMC) stay untouched. Scoring a probability from the placeholder normal is not a claim that the normal is the model.

## What the roadmap asked for, and what changed

The milestone text asked for five things:

- Brier score and log loss, unit-tested against known values. Kept.
- A calibration plot of predicted probability against realized rate. Kept, as ten equal-width bins, a markdown table, and an SVG.
- Edge realization: predicted edge versus realized return. Not built. Replaced with a disagreement count against the pre-tip yes mid.
- A markdown report in `docs/results/`. Kept. The command is still `python -m app.backtest.run`.
- A CI smoke test of one week and five players that fails if calibration drifts badly. The synthetic week is kept. The drift failure is not.

The roadmap file on this branch records those three branch points as choices, not as open defaults.

## Decisions

### The probability is the upper tail of the stored normal.

M3 stores mean, std, and normal 10/50/90 quantiles. It does not store P(over). Brier needs a probability of a binary outcome. The outcome is the one M3 already uses: stat >= line, matching Kalshi "X+" and `floor_strike`.

P(X >= line) = 1 - Φ((line - mean) / std), with Φ from `math.erf`. No SciPy. The test locks Φ's upper tail at z = 1 to the published value 0.15865525393145707, and locks z = 0 to exactly 0.5.

Rejected: a Bernoulli row per strike inside M3. The provenance for M3 already rejected that. M4 reads the distribution M3 stored.

Rejected: a continuity correction (shifting the line by 0.5 before the cdf). The line is already the Kalshi strike, often an x.5 number, and the normal is a placeholder. A second adjustment would be a second arbitrary constant. M6 can replace the distribution.

The std floor of 0.5 from M3 means this probability is never a step function. A player who scored the same number five times still gets a tail. That floor was a numerical guard. It now also keeps log loss finite for those players, together with the clip below.

### Brier is unclipped. Log loss is clipped at 1e-6.

Brier of a probability 0 against an outcome 1 is exactly 1. Clipping it would hide a confident miss. Log loss of the same pair is infinite, which would make one contract erase a month. Log loss clips to [1e-6, 1 - 1e-6]. Brier does not. The tests lock both.

### Ten equal-width bins, empty bins kept.

The roadmap default said "deciles of predicted probability," which can mean equal-count bins. Equal-count bins on a baseline that often says "about 0.4" would each contain a similar probability, and the diagram would look calibrated because of the cut. Equal-width bins on [0, 1] show the pile-up and leave the empty regions empty.

Calibration error is the count-weighted mean of |realized rate - mean predicted probability| inside occupied bins. Empty bins are left out of the average and left in the table. A 5 percentage point budget from the PRD is not a pass/fail gate here. The number is printed. The baseline is not expected to meet a calibration budget the Bayesian model has not been built for.

### The chart is an SVG, not a matplotlib figure.

The diagram is a diagonal and one circle per occupied bin. Radius grows with the count and caps at 16 extra pixels. An SVG is text, diffs in git, and does not add a dependency. The markdown table is the part a reader can use without rendering the image.

Rejected: matplotlib or a notebook figure. Heavier than the chart, and CI would then need the library to import the report module.

### Disagreement is a count. There is no return.

The roadmap asked for predicted edge versus realized return. ADR-3 already defines the market probability as (yes_bid + yes_ask) / 2, and it says the historical REST backfill has settlements, not the book from before polling. The open question in that ADR ("mid versus last trade") is closed here: the mid. `last_price` is a trade print. It can sit outside the spread, and it is not the book at decision time.

A quote is usable only when `quoted_at <= prediction_time` and `ingested_at <= prediction_time`. The same two-clock rule as box scores. A quote that was true at noon and loaded in June is hidden from a November replay. A one-sided book and a crossed book (ask below bid) return no mid. They are not filled from `last_price`.

When a mid exists and the model probability differs from it, the trial counts as a hit if the outcome matches the side the model placed above the mid. The report states the count. It does not multiply by a price, subtract a fee, or call the result an edge.

Rejected: dollar return, expected value, and "the model beat the market." Those sentences need a trading rule and a price that was knowable at 16:00 UTC. Most historical markets will have no such snapshot. Printing a return from the settlement, or from a snapshot taken after tip, would be the leak M3 refused to paper over.

Rejected: a `backtest_runs` table. The PRD lists one. The milestone's artifact is the markdown report. A table becomes useful when two model versions have to be compared side by side. That is M5's problem. M4 does not migrate.

### Each contract is one probability trial. Hit rate is unchanged.

Hit rate still counts each distinct line once, as M3 defined it. Brier and log loss count each ticker once, because each ticker has its own line and its own book. Five strikes on one player are five contracts. The report says so. MAE still counts the player-prop once.

### The CI smoke test does not fail on a bad curve.

`test_ci_smoke_synthetic_week_has_known_brier` builds 35 contracts: five players, seven days, probability 0.25, outcome 0. Brier is 0.0625. Calibration error is 0.25. The test asserts the Brier line and asserts the error equals 0.25. It would be a broken test if a 0.25 gap failed the job, because that gap is the fixture.

A real five-player week would move around by sampling noise, and GitHub Actions does not start Postgres or load the season. A drift gate there would either skip (and a skip is not a pass) or fail at random. The existing pytest step is the CI job. No new workflow.

`--synthetic` regenerates `docs/results/m4-calibration-synthetic.md` without opening the database. The banner says the rows are typed in.

### The real month is still run with both clocks on.

Acceptance asks for a report over a real month. The command is the same replay. If the month's box scores were ingested after the 16:00 UTC clock on those game dates, the probability section says it was not scored. That report is the result. It is not replaced with a synthetic curve wearing the month's dates.

## What the local database did on 6 Nov 2026

Two replays, both committed by the command (same version skips if the row is already there).

`python -m app.backtest.run --start 2025-11-01 --end 2025-11-30` is the real month. 219 games, 5,157 abstentions, 0 forecasts. Kalshi coverage exists in that month. Box scores for it were bulk-loaded in May and June 2026, so the 16:00 UTC clock cannot see them. The report is the empty-probability case: `docs/results/m4-calibration-2025-11-01-2025-11-30.md`.

`python -m app.backtest.run --start 2026-06-03 --end 2026-06-13` is five Finals games, the first dates whose 16:00 UTC clock sits after the 31 May 2026 bulk load. 78,602 player-game rows are visible at 1 Jun 2026 16:00 UTC. Playoff rows loaded on 15 Jun 2026 are still hidden, so the 15-game window for those Finals is the history that had already been ingested, which is mostly the regular season.

That run scored 168 forecasts, MAE 3.548 on 168 player-props, hit rate 73/105 = 0.695, Brier 0.177592 on 105 contracts, log loss 0.522516, calibration error 0.124035. `market_snapshots` has 0 rows, so the disagreement count is empty. A constant probability of 0.5 would have Brier 0.25 on any outcomes; 0.178 is lower than that on these 105 contracts. The 0.7 to 0.8 bin predicted 0.763 and realized 0.462, and the 0.9 to 1.0 bin predicted 0.950 and realized 0.824. The placeholder normal is over-confident in the upper bins on this sample. Five games do not close the M3 "beats 50% on a held-out month" line, and none of these numbers is a claim of an edge.

## What I would not defend

- The normal tail as a basketball probability. It will be over-confident in the tails for a skewed counting stat. It exists so Brier has an input that matches the row M3 stored. If the reliability diagram, once a month is actually visible, piles every contract into one bin, the plot has done its job and the normal should be retired in M6, not patched with another coefficient.
- Scoring every strike as its own trial. A player with eight point lines moves Brier more than a player with one. That matches "each contract is a forecast of a binary," and it does not match "each player-game is one forecast." MAE still treats the player-prop once. If a later comparison needs one trial per player-prop, the closest strike is the wrong choice (it uses the prediction to pick the line). A predeclared strike, such as the line nearest 0.5 in the market, would be a separate decision.
- Leaving the PRD's 5 percentage point calibration budget as a printed number. An interviewer can ask for the gate. The answer is that the budget is for the model that has a posterior. Applying it to this baseline, on a month the clock cannot see, would be a green check with no content.

## Tests that lock the choices

- `test_calibration.py`: normal tail at 0 and at z = 1, Brier of three pairs, log loss of two pairs, clip at 1e-6, equal-width bins and a 0.05 error, probability 1 in the last bin, disagreement skipping ties and missing quotes, yes mid rejecting a one-sided or crossed book, SVG contains a circle, synthetic week Brier is 0.062500 and its calibration error of 0.25 does not fail the test.
- `test_calibration_db.py`: a quote ingested after the clock is hidden; a quote after the clock is hidden; the later visible mid wins and `last_price` is ignored; a missing ask is not a mid.
- `test_baseline_db.py`: the existing one-line replay now also records one probability trial, outcome over, no quote, probability below one half. Mean 20 against a line of 22.5.

## Files

- `backend/app/backtest/metrics.py` holds the arithmetic and the markdown block.
- `backend/app/backtest/plots.py` writes the SVG.
- `backend/app/backtest/quotes.py` reads the latest visible mid.
- `backend/app/backtest/run.py` is still the replay command. It now scores contracts and accepts `--synthetic`.
