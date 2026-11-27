# Architecture Decision Records

ADR-1 and ADR-2 are the records on `main`. ADR-3 (Kalshi market schema) is drafted on branch `kalshi-pipe` and is not merged. The blank structure used to draft these lives in `docs/adr-template.md`.

---

## ADR-1: M1 Schema Design for Point-in-Time Correctness

### Status

ADR-1, 2026-05-17. 

### Context


We need to make sure that this project prevents data leakages and ensures honest backtests.
We want to ensure that the predictions made at a certain point say 
`as_of` were made not knowing facts that the model did not know at that point.
Simple stuff like in autoregression, everything in the future
was set to -1. 

The schema directly addresses point-in-time correctness through directly enforcing 
`event_time` and `ingested_at` to make sure that our backtest queries filter on both of these.
if something was ingested today it must not appear in a backtest set to yesterday.
Enforced in queries.py - query_player_game_logs

Remember that the M0 gave us a backend skeleton, Postgres in docker-compose, Alembic
scaffolding, and the four-table layout for `backend/app/` (data, models,
backtest, alerts).

Tests are wrapped by an outer transaction that prevents our tests from 
messing with our dev db. 

### Decision

- Six tables in M1: `players`, `teams`, `games`, `game_results`,
  `player_game_logs`, `request_cache`.
- Fact tables (`games`, `game_results`, `player_game_logs`) carry both
  `event_time` and `ingested_at`. Identity tables (`players`, `teams`)
  carry `created_at` only.
- `teams` is a single table keyed by NBA official team ID.
- `game_results` is separate from `games` and append-only. New observed
  results add a row with a later `ingested_at` instead of overwriting.
- `player_game_logs` uses a surrogate primary key so future versions of
  the same `(player_id, game_id)` can exist at same time when corrections arrive.
- Historical query helpers must take `as_of` as a keyword-only argument using the `*`.
- `request_cache` lives in Postgres. Every `nba_api` call is keyed,
  cached, and served from cache on repeat.
- Bulk historical loading uses `nba_api`'s `LeagueGameLog` endpoint
- Raw `nba_api` responses are stored in a `raw_data` JSONB column on the
  fact tables so the source-of-truth row is always recoverable.

### Consequences

#### Positive

- Every backtest query has a clean point-in-time filter pattern, and the
  schema makes it the obvious thing to write.
- Stat corrections are representable as new rows. Old backtests stay
  reproducible.
- The `request_cache` table makes bulk loads idempotent and lets us replay
  ingestion without hitting rate limits.
- Storing `raw_data` JSONB means schema decisions can be revisited without
  re-fetching from the NBA.

#### Negative

- Six tables instead of three or four. More joins for some queries.
- Storage grows with append-only versioning and raw response bodies. Fine
  at our scale but can not be ignored. 
- Raw SQL can hypothetically still get through the query helpers. Our `as_of` only
  protects callers who use the helpers. Code review and regression test to extra ensure this. 
- `game_results` separate from `games` is a real extra load for new
  contributors. 

### Alternatives Considered

#### Deriving `player_game_logs` from shufinskiy play-by-play

Rejected. The notebook exploration confirmed shufinskiy is raw event data
(574k rows for one season, no `PTS`/`REB`/`AST`/`MIN`/`GAME_DATE` columns).
Deriving box scores from events would require a substitution/minutes
pipeline that is too complicated. Pushed back to maybe milestone 7 
and perhaps forever. `nba_api` returns box scores directly.

#### Switching the bulk source to the eoinamoore Kaggle dataset

Considered and rejected. Thought about replacing `nba_api`
bulk loading with a maintained Kaggle CSV. The rate-limit concern was based on per-game API calls, but
 `LeagueGameLog`
returns a full season in one call. So the kaggle-dependency was not worth it. 

### Open Questions

- Maybe temporal player names need a similar `players` + `player_names`
  split eventually. Revisit.
- Whether to add denormalized stat snapshots for the dashboard after we
  profile real queries.
- How to represent in-progress games where final stats aren't posted yet.
  Most likely through just a `status` column on `game_results` with values `final`,
  `in_progress`, `postponed`. Worth deciding before we start making the daily job
  or tbh the every other day job.
- Whether `request_cache` TTLs should be per-endpoint or global. Global
  with a sensible default should be fine for v1.

---

## ADR-2: Use `curl_cffi` to Talk to `stats.nba.com`

### Status

Accepted, 2026-05-30.

### Context (the ELI15 version)

When your browser visits a website, first step is **TLS handshake**. Fancy handshake where both sides agree on how to encrypt the rest of the conversation. Handshake has a "shape", the exact order of cipher suites the client offers, the extensions it lists, the curves it advertises and etc. This shape is the **TLS fingerprint**.

Real browsers like Chrome and stuff have very specific fingerprints. Anti-bot companies such as Akamai (which the nba utilizes) have memorized what real browser fingerprints look like. They use the fingerprint to decide whether you're a real human in a browser or a script pretending to be one.

My mistake

 **Every Python HTTP library (`requests`, `httpx`, `urllib3`) shares the same TLS fingerprint, because they all use the same underlying library (`OpenSSL` via Python's `ssl` module)**. That fingerprint is very obviously not-a-browser.

When you hit `stats.nba.com` from a Python script:
1. The TCP connection opens.
2. The TLS handshake completes (Akamai lets you in to look like a normal server response).
3. Your request goes out.
4. **The server never responds.** Akamai silently drops the response because the fingerprint screams "scraper."

Uh oh thought everything was over and would have to switch to like kaggle. 

### The fix

**`curl_cffi`** is an open-source Python package (MIT licensed, free, `pip install curl_cffi`). Instead of using Python's `ssl` module, it uses a special build of `libcurl` that's linked against BoringSSL which is Chrome's TLS library. So when `curl_cffi` makes a request with `impersonate="chrome120"`, the TLS handshake on the wire is identical to Chrome 120.

Akamai's fingerprint check passes. The response comes back. Everything works.

### Decision

- Use `curl_cffi.requests.Session(impersonate="chrome120")` for all outbound HTTP in `CachedHttpClient`.
- Keep the rest of the cache wrapper (lookup → fetch → store) unchanged. The TLS bit is the only part that mattered.
- For tests, inject a `FakeSession` (in `backend/tests/_fakes.py`) instead of using HTTP mocking libraries.

### Consequences

#### Positive

- `stats.nba.com` is reachable. The original M1 scope (free public NBA API + cache) works as designed.
- No infrastructure changes. `curl_cffi` is a pip package; deploys to Railway with no special config.
- No paid dependencies. Stays inside the v1 budget constraint.
- Same fix unlocks any other Akamai/Cloudflare-protected NBA endpoint we might want later.

#### Negative

- One more dependency to maintain. `curl_cffi` is well-maintained but smaller-community than `httpx`. If it goes unmaintained, we'd have to switch (probably to `tls-client` or a headless browser).

### Open Questions

- Will Chrome's TLS fingerprint shift enough in the next year to require bumping the `impersonate=` profile?

---

## ADR-3: M2 Schema for Kalshi Market Data

### Status

Drafted 2026-05-31. Ronnie to rewrite in his voice.

### Context

M2 brings Kalshi NBA prop market data into Postgres. We need live snapshots
every 5 minutes for active markets and a one-time backfill of settled
markets from Nov 2025 (when Kalshi added NBA prop coverage) onward.

Two design constraints shape the schema:

1. **Point-in-time correctness still applies.** A backtest asking "what was
   the price on player X, prop Y at time T" must return the latest snapshot
   with `quoted_at <= T` and `ingested_at <= T`. Same pattern as M1's fact
   tables.
2. **Kalshi's market identity is the non-mechanical work.** Each Kalshi
   market is a binary Yes/No at one strike (not an over/under with two
   sides). A single game and player produces multiple market tickers, one
   per line. The market ticker `KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35`
   needs to map to `(player_id, game_id, prop_type, line)` in M1's schema.

We probed the public REST API
(`https://api.elections.kalshi.com/trade-api/v2/markets`) to confirm the
ticker format, the price fields, and that `?status=settled` returns the
finalized historical markets we need for backtest.

### Decision

**Three new tables plus one alias table.**

- `markets` — identity row per Kalshi ticker. PK is `ticker` (string).
  Holds the immutable market identity (series, event_ticker, prop_type,
  line, strike_type, open_time, close_time, rules_primary text) plus
  resolved FKs (`player_id` → `players`, `game_id` → `games`, both nullable
  until alias resolution succeeds). Carries `created_at` and `ingested_at`.
  Stores `raw_data` JSONB so we can re-resolve if the alias table grows.

- `market_snapshots` — fact table. **Composite PK `(ticker, quoted_at)`.**
  Holds `yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `last_price`, `volume`,
  `open_interest`, `liquidity` as floats. `quoted_at` is the `event_time`
  analog from M1 (the moment the price was true). Carries `ingested_at`.
  `raw_data` JSONB for the full Kalshi market object at snapshot time.
  Index on `(ticker, quoted_at DESC)` for the "latest snapshot at or
  before T" query pattern.

- `market_settlements` — fact table. PK is `ticker` (one settlement per
  market). Holds `result` ("yes" | "no"), `settlement_value` in dollars,
  `settled_at`, `ingested_at`, `raw_data`.

- `kalshi_player_aliases` — mapping table. PK is `kalshi_player_name`
  (the English name extracted from `rules_primary`, e.g. "Victor
  Wembanyama"). Column `player_id` FK → `players.player_id`. Carries
  `created_at`. Seeded semi-manually for the ~50 Kalshi-covered players.

**No `kalshi_game_aliases` table.** Game resolution joins directly against
M1's `games` table on `game_date` + home/away team abbreviations. The
Kalshi event_ticker (`KXNBAPTS-26MAY30SASOKC`) decomposes cleanly to
`(2026-05-30, SAS away, OKC home)` and M1's `Game.game_date` (already a
`date` column) makes this a clean equality join through the `teams` table.

**One Kalshi market = one row in `markets`.** A Wembanyama "30+ points"
market and "35+ points" market for the same game are two distinct tickers
and two distinct rows, distinguished by the `line` column. The Yes side
is "scores ≥ line"; No is "scores < line".

**All four price legs stored on snapshots.** `yes_bid`, `yes_ask`,
`no_bid`, `no_ask`. Not redundant on a binary market: `yes_ask + no_ask`
should sum near 1.00 in liquid markets but bid sides won't. Storing all
four costs little and lets us reason about spread/liquidity later.

**Snapshot job gating: simplest version.** Every 5 minutes, fetch all
`markets` with `close_time > now`. No filtering by NBA game windows. If
there are no active markets the snapshot pass is a single empty fetch.

**Alias resolution at ingest time.** When a market is first seen, parse
`rules_primary` for the player name, look up `kalshi_player_aliases`,
parse the event_ticker for `(date, away, home)`, look up the M1 `games`
row, populate `markets.player_id` and `markets.game_id`. Unresolved
markets get stored with NULL FKs and counted as `aliases_unmapped` in
the load summary. A later pass can re-resolve unmapped markets when the
alias table grows.

**Same reusable infrastructure.** `CachedHttpClient`, `FakeSession`,
`load_season`-shape orchestration with date-window args, per-batch
`session.flush()` + caller `commit()`, APScheduler `AsyncIOScheduler`
gated by `SCHEDULER_ENABLED`. No per-source HTTP client switching.

### Consequences

#### Positive

- Backtests against Kalshi work with the same `as_of` filter pattern as
  M1: `SELECT ... FROM market_snapshots WHERE ticker = ? AND quoted_at <= ?
  AND ingested_at <= ? ORDER BY quoted_at DESC LIMIT 1`.
- Multiple strikes per (player, game) fall out for free. Whichever line
  the model wants to evaluate against has its own row of snapshots.
- Alias-resolution failures are recoverable. Raw Kalshi text is preserved
  in `markets.raw_data` and the source columns; growing the alias table
  later re-resolves stale rows.
- The snapshot composite PK gives idempotency for free. Re-running the
  snapshot job within the same 5-min window inserts zero new rows because
  `(ticker, quoted_at)` already exists.
- Three tables matches M1's separation: identity (`markets`) plus
  facts (`market_snapshots`, `market_settlements`). Familiar pattern.

#### Negative

- The alias table is manual seeding work. ~50 players is small but real;
  the first run will surface unmapped names that need adding by hand.
- Storing all four bid/ask legs plus volume + OI + liquidity per snapshot
  is fatter than necessary for v1's edge computation. Disk cost is small.
- `markets` rows are mutable for `close_time` (Kalshi shifts it on early
  close) and `player_id`/`game_id` (resolved later). Not append-only.
  Trade-off: simpler queries, but updates require us to be careful that
  raw_data is updated whenever close_time changes.
- Game resolution depends on Kalshi's `event_ticker` date/abbreviations
  matching NBA's `LeagueGameLog`. Robust for clean cases, fragile for
  rare cases (rescheduled games, neutral-site games, abbreviation
  drift). Documented as an open question.

### Alternatives Considered

#### Single "over/under at line L" market row with both sides

Rejected. Kalshi serves each strike as its own binary market with its own
ticker, open/close times, and price legs. Forcing a two-sided abstraction
on top would lose information (yes_ask + no_ask doesn't always equal 1.00
mid-trade) and would require us to invent a pairing rule that Kalshi
itself doesn't expose.

#### Separate `kalshi_game_aliases` mapping table

Considered and rejected. M1's `games` table already carries the canonical
game identity keyed by NBA `game_id`, with `event_time` and the team FKs.
The Kalshi event_ticker `26MAY30SASOKC` decodes deterministically to
`(2026-05-30, SAS, OKC)`, which joins directly against `games` through
the `teams` table by abbreviation. A separate alias table would duplicate
information that M1 already has.

#### Mid-price-only snapshots

Considered (would halve the snapshot rows' price columns) and rejected.
Spread and liquidity are signal we want to study later, and the four-leg
storage cost is trivial.

#### Snapshot job gated by NBA game windows

Considered (only poll within ±3h of an actual game tipoff). Rejected for
v1 in favor of "poll any market with `close_time > now`." The tighter
gating is a v1.1 optimization once we observe actual call volume.

#### Store snapshots in a single wide row keyed by `ticker` with
arrays / JSONB time series

Rejected. Querying "snapshot at or before T" against a JSON array
requires unnesting and is unfriendly to the backtest query path. A
flat `market_snapshots` row per `(ticker, quoted_at)` is the natural
shape and the index on `quoted_at DESC` makes the lookup cheap.

#### Append-only `markets` (no in-place updates)

Considered, given M1's append-only `game_results`. Rejected because
markets carry resolved FKs that we want to backfill *after* the row
exists, and `close_time` legitimately shifts when Kalshi triggers an
early close. Treating `markets` as identity-like (PK = ticker, row
updates on re-observation) keeps queries simple. `raw_data` JSONB
preserves the historical view if we need it.

### Open Questions

- **Mid-price vs last-trade for edge computation.** `((yes_bid + yes_ask)
  / 2)` is the natural market-implied probability; `last_price_dollars`
  is the most recent trade. v1 stores both; the modeling pipeline picks
  one in M3.
- **Player disambiguation when the ticker carries a suffix digit** (e.g.
  `SASVWEMBANYAMA1`). The `1` suffix appears unused in our sampled data
  but presumably handles same-name same-team collisions. Watch for it
  in real coverage; the alias table is keyed on the English name from
  `rules_primary`, which sidesteps the suffix.
- **Historical snapshots before our system started polling.** Kalshi's
  REST exposes settled markets and their final state but not the price
  history. The backfill captures settlements; live snapshots only exist
  going forward.
- **Rescheduled or neutral-site games.** Kalshi's event_ticker date may
  not match NBA's `GAME_DATE` if a game is postponed. Probably rare
  enough to handle as alias-resolution failures (NULL FKs) and patch
  manually.
- **Multi-leg props (PRA, PR, RA, threes, etc.).** Out of scope v1 per
  PRD §9, but their series tickers (`KXNBAPRA`, `KXNBAPR`, `KXNBARA`,
  `KXNBA3PT`) exist and would slot into this schema by adding a
  `prop_type` value. The schema doesn't preclude them.

---

## ADR-4: Prop posteriors around the M5 booster

### Status

ADR-4, 2026-11-26. This records the models that were sampled for the M6 close. The agent typed the likelihoods. It is not a claim that the priors were settled by a separate reading.

### Context

M5 stores one residual width around the XGBoost mean. M6 replaces that width with a posterior for one prop at a time. The holdout is the M5 date cut, headline rest at most 14 days, and the booster for a holdout row is trained only on earlier dates.

A free player intercept added to `beta * xgb_mean` was not a separate scale on points or on assists. On the full points population the slope of those intercepts on the player's mean booster prediction correlated with `beta` at -0.864. On the full assists population that correlation was -0.827. The intercepts were a second copy of the slope.

### Decision

- Each prop uses a normal left-censored at 0. A positive observation uses the normal density. A zero uses the probability that the latent normal is at or below 0. The width is one shared `sigma`, half-normal with scale 8. `tau` is half-normal with scale 2. `alpha` is `tau` times a standard normal.
- Points and rebounds: location is `beta * xgb_mean + alpha`, with `beta` normal mean 1 and standard deviation 0.25, and the slope of `alpha` on the player's mean out-of-fold booster prediction removed.
- Assists: location is `1 * xgb_mean + alpha`. `beta` is the constant 1. The orthogonal constraint lost the subset Brier on assists, so it is not the stored assists model.
- The sampler's training covariate is the out-of-fold booster prediction from five expanding date blocks. Holdout rows use the booster trained on every training date. A player with no training intercept keeps `alpha` at 0.
- The reported fit is NUTS: 4 chains, 1,000 tune, 2,000 draws, target accept 0.9, seed 0. The stored row is the posterior predictive mean, sample standard deviation, and 10/50/90 of an observation draw `y ~ N(mu, sigma)` (shared width; gamma form when used), then stopped at 0 when the model is left-censored. Storing the location `mu = beta * xgb_mean + alpha` alone is wrong: that is the posterior of the mean, and the dashboard would show spike densities. `payload.distribution` is `posterior`. `payload.predictive` is `observation`. `model_version` is `pymc-m6-v1`.

### Consequences

### Positive

- Each prop's posterior Brier on every headline contract of that prop is lower than the M5 residual band on those contracts. The three contract sets are the 18,878 M5 contracts.
- Points and rebounds keep a free `beta` near 1 without the intercept absorbing it. Assists keeps the booster mean as the location scale.
- One prediction row per scored player-game can be checked against every line of that prop.

### Negative

- The three props are not the same parameterization. Assists needed a fixed `beta`. Points and rebounds needed the orthogonal intercept.
- Removing the points intercept slope gave back some of the Brier the unconstrained intercept had won. The unconstrained points Brier was 0.156784. The stored points fit is 0.157591.
- The free-`beta` assists sample had the better Brier, 0.146534 against the stored 0.147770, and was refused because the intercepts absorbed `beta`.

### Alternatives Considered

Leaving the intercept unconstrained on points was rejected. That sample mixed and had the better Brier, and the intercepts absorbed `beta`.

An orthogonal intercept on assists was rejected. The 40-player subset lost the residual band.

A free `beta` on the full assists population was rejected. The Brier won and the slope correlation was -0.827.

A width that grows with the booster mean was rejected on points. The coefficient was positive and identified, and the out-of-fold sample did not produce a usable posterior.

### Open Questions

- Whether a single parameterization can cover all three props without a prop-specific constraint.
- Whether Ronnie replaces these priors. A replacement is a new `model_version` and a new sample, not an edit of `pymc-m6-v1`.

---

## ADR-5: Lineup redistribution from starter flags, injury as trigger

### Status

ADR-5, 2026-11-27. M7 close record for the lineup-conditional layer.

### Context

Injury news arrives before tip. Box scores arrive after. The lineup layer needs historical games where a usual starter was missing so teammate counting-stat means can shift when a live claim says that starter is out.

`LeagueGameLog` rows do not carry who started. Traditional box scores expose `START_POSITION`.

### Decision

- Backfill `player_game_logs.started` from `boxscoretraditionalv2` `START_POSITION`. Non-empty means started. Null means not yet backfilled.
- A usual starter is a player who started in at least 6 of the prior 10 team games under the feature clocks.
- Fit one shrunk mean difference per `(injured_id, beneficiary_id, prop)`: mean(stat | injured usual starter out) minus mean(stat | injured started), shrunk toward 0 with weight `n_out / (n_out + 8)`.
- Persist effects as `models/lineup_m7_effects.json`. Store adjusted forecasts as `lineup-m7-v1` beside existing model versions. Do not overwrite them.
- Live trigger is `injury_signals` with `claim_type` in `{out, doubtful}` and confidence at least 0.5. Classification uses Claude Haiku 4.5 (`m7-injury-v1` prompt). Official reports use `nbainjuries`; ESPN and Bleacher Report use RSS.
- Feature reads of `injury_signals` filter `event_time < as_of` and `available_at <= as_of`.

### Consequences

### Positive

- Training labels match box-score starters. Inference matches the news the system scrapes.
- The Embiid to Maxey synthetic test asserts a fitted positive points lift, not a hand-tuned constant.

### Negative

- Starter backfill is one HTTP call per game and depends on `stats.nba.com`.
- `nbainjuries` needs Java for PDF table extraction. RSS can still prove scrape to store when an official PDF is missing.
- Daily production predictions stay on `baseline-m3-v1` until a reliable pre-tip `Game` path exists.

### Alternatives Considered

Top-5 minutes as the starter label was rejected for the published model. It is circular with the outcome.

Training only on injury-report archives was rejected. Report history is messier than box scores for "starter was out."

A hard-coded Embiid-out to Maxey points bump was rejected as product behavior.

### Open Questions

- Whether a hierarchical Bayesian redistribution with player-specific slopes beats the shrunk mean difference on a later holdout.
- Whether Sonnet fallback is needed. The prior open question rested on a held-out Haiku joint accuracy of 1.000; that score is retracted (template eval + empty-name / regex scoring — see `docs/results/m7-llm.md`). Revisit only after a real scraped held-out exists.