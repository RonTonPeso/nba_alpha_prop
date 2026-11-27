# M7 plan: injury signals and lineup redistribution

Written 27 Nov 2026, before implementation. Results after the proving
commands land in `docs/provenance/m7-injury.md`. The audience is someone
asking why training labels and live triggers are not the same object.

## Where this aims

`docs/Roadmap.md` M7 acceptance:

- An injury news item is classified and stored with structured fields
  within 5 minutes of being scraped.
- A simulated "Embiid out" event causes Maxey's projection to update
  meaningfully (synthetic data; direction and magnitude).
- LLM classification accuracy on a held-out test set is documented.

## Decisions

### Starter history comes from box-score `START_POSITION`. Injury reports trigger at inference.

The lineup model needs games where a usual starter was missing. LeagueGameLog
rows in `player_game_logs` have minutes and counting stats, not who started.
Traditional box scores expose `START_POSITION`. Non-empty means started.
That flag is backfilled onto `player_game_logs.started`. "Usual starter out"
is derived from recent started games under the feature clocks.

Live updates do not wait for a box score. Official reports and RSS become
`injury_signals` through Haiku. An Out or Doubtful claim for a usual starter
is the trigger that applies the fitted teammate shifts.

Rejected: top-5 minutes as the published starter label. Minutes are
outcomes of the night; using them to invent "out" labels is circular.
A minutes proxy stays only if `START_POSITION` backfill is proven blocked,
and that block has to be in the results note first.

Rejected: training only on injury-report history. Report archives are
messier than box scores, and the roadmap sentence is "historical games
where starters were out."

### Adjusted forecasts are a new `model_version`, not an overwrite.

`lineup-m7-v1` stores the shifted mean beside `baseline-m3-v1`,
`xgb-m5-v1`, and `pymc-m6-v1`. The payload names the signals and the
starters-out that drove the shift. Daily production stays on baseline
until a pre-tip `Game` path exists. M7 closes on the synthetic Embiid
test and stored adjusted rows, not on flipping the 16:00 UTC job.

### Five-minute acceptance is a timed command. Scheduler stays off.

`python -m app.data.injury.run --timed` scrapes, classifies, and stores.
Wall-clock under 300 seconds is the proof. Jobs `injury_official` and
`injury_rss` are registered. `SCHEDULER_ENABLED` defaults false, same as
M5 and M6. A live Railway tick is not the close.

### Haiku first. Sonnet only on a failed accuracy bar.

Held-out exact match on player identity and `claim_type` must clear 85%.
Below that, low-confidence rows may fall back to Sonnet and the report
says so. Twitter stays out.

### Play-by-play stays deferred.

Shufinskiy is raw events. Starter flags do not need it if traditional
box scores answer. Loading PBP does not close M7.

## What would make this plan wrong

- Traditional box scores lack usable `START_POSITION` for loaded seasons.
  Stop before any minutes proxy; write the failure in the results note.
- Haiku held-out accuracy stays under 85% even with Sonnet fallback.
  The LLM acceptance line stays open.
- The fitted Embiid to Maxey points effect is near zero or wrong-signed.
  Do not invent a constant to pass the synthetic test.
- Scrape to classify cannot stay under five minutes on a cold path.

## Not verified yet

- Whether `stats.nba.com` `boxscoretraditionalv2` returns `START_POSITION`
  for every game already in the local database.
- Whether a real Anthropic key and a reachable Postgres are present when
  the timed pipeline and held-out eval run.
- The sign and magnitude of Embiid-out on Maxey points in this database.
