# Architecture Decision Records

---

## ADR-1: M1 Schema Design for Point-in-Time Correctness

### Status

ADR-1, 2026-05-17. 

### Context


We need to make sure that this project prevents data leakages and ensures honest backtests.
We want to ensure that the the predictions made at a certain point say 
`as_of` were made not knowing facts that the model did not know at that point.
Simple stuff like in autoregression, everything in the future
was set to -1. 

The schema directly addresses point-in-time correctness through directly enforcing 
`event_time` and `ingested_at` to make sure that our backtest queries filter on both of these.
if something was ingested today it must not appear in a backset set to yesterday.
Enforced in quieries.py - query_player_game_logs

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
- `player_game_logs` uses a surrogate(CHANGE THIS WORD) primary key so future versions of
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
pipeline that is too complicated. Pushed back to maybe mileston 7 
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




# ADR Template

## Skeleton

Use this as the structure for the real ADR. Each section has a short
prompt for what belongs there. Keep your prose terse. The reader is a
future engineer trying to understand a decision.

### Context

Two or three short paragraphs. Establish:

- What problem this ADR addresses (one sentence).
- The constraint that forces a non-trivial design (one sentence). For this
  ADR, that constraint is point-in-time correctness for backtesting.
- Any prior state worth noting (existing tables, prior attempts, M0 work).

### Decision

Bulleted list. Each bullet is one design choice you made. Keep the bullets
terse; the reasoning lives in the next two sections. Example shape:

- One sentence per decision.
- Use the present tense ("Fact tables carry...").
- Don't justify here. Just state.

### Consequences

#### Positive

- What this design enables. Three to six bullets.

#### Negative

- What this design costs. Three to six bullets. Be honest about the costs.
  An ADR with no negative consequences reads like marketing.

### Alternatives Considered

This is the most important section. For each rejected alternative, write a
short paragraph: what the alternative was, and why you rejected it. This
is where your engineering judgment shows up. A reader skimming the ADR
should be able to learn what you ruled out and why.

Recommended alternatives to cover for this ADR:

- Mutable game rows (no append-only results table).
- Denormalized team names directly on `player_game_logs`.
- Full event sourcing for every table.
- Deriving `player_game_logs` from shufinskiy play-by-play.
- Switching the bulk source to the eoinamoore Kaggle dataset.
- `franchises` + `franchise_identities` split for temporal team identity.

### Open Questions

Things you have not decided yet, or intend to revisit. Be honest. The point
of writing these down is so future-you knows what's still load-bearing on
later decisions.

---

## ADR-2: Use `curl_cffi` to Talk to `stats.nba.com`

### Status

Accepted, 2026-05-30.

### Context (the ELI15 version)

When your browser visits a website, first step is **TLS handshake**. Fancy handshake where both sides agree on how to encrypt the rest of the conversation. Handshake has a "shape", the exact order of cipher suites the client offers, the extensions it lists, the curves it advertises and etc. This shape is the **TLS fingerprint**.

Real browsers like Chrome and stuff have very specific fingerprints. Anti-bot companies such as Akami (which the nba utilizes) have memorized what real browser fingerprints look like. They use the fingerprint to decide whether you're a real human in a browser or a script pretending to be one.

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