
# Process notes

Stack-ordered: newest entries pushed onto the top. Scroll down for older work.

---

# M4 start: calibration on the baseline replay (2026-11-06)

Branch `m4-calibration` from `origin/main` at `3abadf1` (PR #3 merged).

The interviewer writeup is `docs/provenance/m4-calibration.md`. The replay now turns the stored normal into P(stat >= line) and reports Brier, log loss, ten equal-width bins, and an SVG reliability diagram. The market comparison uses the yes mid only when a snapshot is visible at 16:00 UTC. It does not compute a payout. The CI check is a synthetic 5-by-7 week with a known Brier score, and a bad calibration gap does not fail the job.

---

# M3 start: baseline, predictions table, replay harness (2026-11-06)

Started M3 from local `main` at `c65c419` (the Kalshi tip, three commits ahead of origin/main). Branch `m3-baseline`.

The interviewer-facing writeup of the choices is `docs/provenance/m3-baseline.md`. Short version: rolling mean of 15, half-strength home and rest effects estimated inside that window, abstain under 5 games, normal band with a 0.5 std floor, one row per player-prop-game, Kalshi lines joined only at scoring time. Feature reads go through `query_player_game_logs`. `ingested_at` was not dropped to make a 2025 replay look populated.

Quality gates this session: ruff, black, mypy, pytest 76 passed with Postgres up. Alembic revision `c3b1a9e0d4f2` applied to the local database.

Not claimed: hit rate above 50% on a held-out month.

---

# M2 close: snapshot job, scheduler, failure modes, alias seeding, playoffs detour, conftest fix (worked 2026-06-01 through 2026-06-15)

Closed the second half of M2. The snapshot job lives, the scheduler runs both ingest cadences, four named failure-mode tests cover the Kalshi source, the alias table is populated, the historical bulk run is finished and verified, and a detour to load NBA playoffs + Play-In games brought game FK resolution from 53% to 100%. Quality gates pass cleanly: ruff, black, mypy strict, pytest 65/65. README also rewritten as a finished portfolio piece and pushed to public main mid-session.

## `backend/app/data/kalshi_snapshot.py`

The 5-min snapshot job. Reuses helpers from `kalshi_bulk_load.py` (alias maps, `resolve_game_id`), filters Kalshi by `status="active"`, and writes one `MarketSnapshot` per polled market plus opportunistic `MarketSettlement` writes when a polled market carries `result` + `settlement_ts`.

- **Two-pass orchestration.** First pass parses every market across the three series and queues three lists: new-market ORM objects, snapshot ORM objects, settlement ORM objects. Second pass adds + flushes markets, then adds snapshots, flushes, then adds settlements. The flush between markets and snapshots is the FK boundary: `MarketSnapshot.ticker` references `Market.ticker`, so the parent has to land first.
- **Cache TTL strategy.** Per-page fetches use `ttl=timedelta(minutes=4)` so a retry inside the same 5-min tick is cheap (Postgres hit, no Kalshi call), and the next tick refetches. The snapshot's `quoted_at` field still tracks `updated_time` from the API response, so a cache-served response writes the right timestamp; the composite PK dedups when `updated_time` hasn't moved.
- **Status filter plus defensive close_time skip.** Pass `status="active"` to the API to skip already-settled markets, then in the parse loop also skip any row whose `close_time <= now` (a `markets_skipped_closed` counter records these). Belt-and-suspenders against Kalshi returning a stale `active` flag on a market that just expired.
- **Composite PK dedup.** Before adding a `MarketSnapshot`, `session.get(MarketSnapshot, (ticker, quoted_at))` checks the PK; duplicates bump `snapshots_duplicate` and skip. Cheaper than catching an `IntegrityError` and rolling back.
- **`SnapshotSummary` counters:** `markets_seen`, `markets_inserted_new`, `markets_existing`, `markets_errors`, `markets_skipped_closed`, `snapshots_inserted`, `snapshots_duplicate`, `settlements_inserted`, `settlements_existing`, `players_resolved`, `players_unmapped`, `games_resolved`, `games_unmapped`, `unmapped_player_names: set[str]`, `elapsed_seconds`. Pretty-print mirrors `BulkLoadSummary`.

Tests in `backend/tests/test_kalshi_snapshot.py` (6 tests):
1. **Round-trip** seed identity + alias, mock one active market, verify Market + MarketSnapshot rows with FKs resolved and `quoted_at` taken from `updated_time`.
2. **Opportunistic settlement** the polled market carries `result` + `settlement_ts`; one MarketSettlement row written.
3. **Idempotency on composite PK** second tick against same handler with same `updated_time` writes zero new snapshots; `snapshots_duplicate` bumps.
4. **Advancing `updated_time` does insert** a new row appears when Kalshi's `updated_time` moves. To force a refetch between ticks, the test runs `delete(RequestCache)` then `flush()` (mirrors the production 4-min TTL expiry).
5. **Defensive close_time skip** even with `status="active"`, a market whose `close_time` has passed gets skipped; `markets_skipped_closed` bumps.
6. **Unmapped alias fallthrough** without a `KalshiPlayerAlias` row, the market + snapshot still write; `player_id` is left NULL; the name lands in `unmapped_player_names`.

## `backend/app/scheduler.py`

Existing daily-ingest scheduler extended with a second job. Two `add_job` calls, same `AsyncIOScheduler`, same `SCHEDULER_ENABLED` env-var gate via `main.py`'s lifespan:

- `run_daily_ingest` via `CronTrigger(hour=12, minute=0, timezone="UTC")` (unchanged).
- `run_snapshot` via `IntervalTrigger(minutes=5)`, `id="kalshi_snapshot"`, `replace_existing=True`, `misfire_grace_time=60`.

One added test in `backend/tests/test_scheduler.py` asserts both job IDs are present after `make_scheduler()`. No actual cadence test (don't want a sleep-5-min test in CI); the existence assertion is enough plus the integration tests prove the underlying functions work.

## `backend/tests/test_kalshi_failure_modes.py`

Four named tests mirroring M1's `test_failure_modes.py` structure exactly. PRD §6.1 calls for "four specific failure modes per source," so this is the M2 source's matched set:

1. **Timeout** `FakeSession` handler raises `curl_cffi.requests.exceptions.Timeout`. `fetch_markets_page` propagates the exception. `request_cache` query confirms no row stored. Uses `max_retries=0` to avoid sleeping through the cache's backoff schedule.
2. **429 rate limit** handler returns `FakeResponse(429, ...)`. After all retries are exhausted (also pinned at `max_retries=0` so the cache surfaces the error immediately), `HTTPError` propagates and no row is stored.
3. **Malformed JSON** handler returns `FakeResponse(200, raise_on_json=True)`. The cache's `response.json()` call raises; the exception propagates and no row is stored.
4. **Missing field (orchestration)** a synthetic Kalshi response with two markets, one well-formed and one missing `rules_primary`. `load_settled_markets` skips the bad row (bumps `markets_errors`), inserts the good row, and the run completes without crashing. This one runs at the bulk_load layer rather than the cache layer because parser-level schema drift is caught there.

## `backend/app/data/kalshi_seed_aliases.py` + `kalshi_player_aliases.csv`

A CSV-driven seed CLI for the `kalshi_player_aliases` table. The CSV is the versioned artifact (two columns: `kalshi_player_name,player_id`); the CLI reads it and upserts each row. Per-row `session.get(KalshiPlayerAlias, name)` decides insert vs update; a third counter tracks rows that were already correct and skipped. Summary line: `+N inserted, +M updated, K unchanged`.

Test in `backend/tests/test_kalshi_seed_aliases.py` (3 tests): insert-fresh, update-when-player-id-changes, skip-when-unchanged.

## `backend/app/data/kalshi_auto_match_aliases.py`

Helper CLI for populating the CSV from the live unmapped names. Queries `SELECT DISTINCT kalshi_player_name FROM markets WHERE player_id IS NULL`, then tries two passes against `players.current_name`:

1. **Exact-match pass** straightforward dict lookup on the raw name.
2. **Accent-normalized pass** `unicodedata.normalize("NFKD", name)` then encode-ASCII-ignore to strip combining marks. "Nikola Jokić" -> "nikola jokic", "Dennis Schröder" -> "dennis schroder". Ambiguity (multiple players hashing to the same normalized form) is reported, not auto-resolved.

Matches append to the CSV; unmatched names print so the user can hand-resolve nicknames or non-standard spellings. The implementation cost was a hedge against the worst case: I expected ~30 names to need accent-handling and ~10 to need hand resolution. In practice, all 148 names matched exact-string on the first pass. stats.nba.com preserves accents in `current_name`, Kalshi uses the same spelling, so the fallback wasn't needed. The CLI is in place for future seasons regardless.

## Real-data Kalshi bulk run

Ran `uv run python -m app.data.kalshi_bulk_load --min-close-date 2025-11-01` against live Kalshi. First attempt failed with a real HTTP 429 from the production endpoint mid-run (Kalshi's free public API is generous but not unlimited).

Patched `backend/app/data/cache.py::_fetch_with_retry` to add exponential backoff on 429 specifically (independent of the existing timeout retry path). Default `max_retries=3`, `retry_backoff_seconds=1.0`; sleep grows 1s, 2s, 4s. Updated the two pre-existing 429 tests in `test_failure_modes.py` and `test_kalshi_failure_modes.py` to pass `max_retries=0` so they verify the propagate path without sleeping. Added one new test `test_cache_retries_on_429_then_succeeds` (single 429 then 200, returns the 200 body, no exception).

Re-ran. Clean. Summary:
- 19,736 markets ingested across the three series (KXNBAPTS, KXNBAREB, KXNBAAST).
- 18,822 settled, 914 unsettled (open or finalized-without-settlement).
- 148 unique unmapped player names surfaced.
- 10,393 game FKs resolved on the first pass.

## README rewrite + out-of-band publish to main

Mid-session interrupt: rewrote `README.md` as if the project were already finished, written simply enough for a non-technical recruiter to follow. First-person, no em dashes, eight sections (live URL, what the dashboard shows, why I built it, how forecasting works, where injury news comes in, what I'm most proud of, under the hood, repo layout, about me). Includes the curl_cffi war story from M1 as a concrete "what I'd flag in an interview" anecdote.

Published out-of-band: stash everything on `kalshi-pipe`, switch to `main`, `git checkout stash@{0} -- README.md` to pull just that file, commit, push, switch back, pop stash. Direct push to main was initially blocked by a branch protection rule; user removed the rule for the push and re-enabled it after. Commit `072cf9f`.

## The playoffs detour and the Play-In follow-up

Step 7 of the close was supposed to be a quick spot-check after the alias backfill. Two surprises pushed it further:

1. **First post-seed `kalshi_bulk_load` showed `0 game FKs resolved` for the existing rows.** The bulk loader's existing-row branch only bumps `players_resolved` / `games_resolved` when the existing column was NULL. The 10,393 already-resolved game FKs from the pre-seed run were already non-NULL, so the counters stayed at zero on the rerun. Verified with a DB query: 19,736 markets, 19,736 with `player_id`, 0 NULL `player_id`. Worked as intended; the summary line is just easy to misread.
2. **9,343 markets still had NULL `game_id`.** Distribution query showed every one of them fell between `2026-04-14` and `2026-06-03`. The `games` table's latest entry was `2026-04-12`. The gap exactly matched the 2026 NBA Playoffs window. M1's bulk loader was only ever called with `--season-type "Regular Season"`, so playoff games were never loaded.

Loaded playoffs across all four covered seasons (2022-23 through 2025-26) via the existing `bulk_load` CLI's `--season-type Playoffs` choice (already a valid choice from M1, just never exercised). Re-ran `kalshi_bulk_load`: 675 markets still unmapped.

Distribution query on the remaining 675: all on April 14, 15, 17, 2026. Six (away, home) pairs. NBA `games` table had nothing on those dates. Recognized as 2026 Play-In Tournament games (mid-April mini-bracket between regular season and playoffs). M1's CLI choices were `["Regular Season", "Playoffs"]`; the NBA stats API also accepts `"PlayIn"` as a `SeasonType` value. Added `"PlayIn"` to the choices list (`bulk_load.py:299`) and ran it across four seasons. Final rerun of `kalshi_bulk_load`: 675 resolved, 0 unmapped. All 19,736 markets are now joined to a player and a game.

## Conftest fix for new FKs

Local pytest sprouted 14 errors after the M2 schema landed. The shared test fixture `db_session` wipes every table inside an outer transaction at the start of each test, in FK-safe order, so the dev DB's bulk-loaded data is invisible during a test and untouched after. The wipe list was M1-only (`PlayerGameLog, GameResult, Game, Player, Team, RequestCache`). `MarketSnapshot`, `MarketSettlement`, `Market`, and `KalshiPlayerAlias` were missing, so the truncation order failed at `DELETE FROM games` (FK from `markets.game_id`).

Updated `backend/tests/conftest.py` to include all four new tables in the right delete order: snapshots and settlements first (children of `markets`), then `markets` and `kalshi_player_aliases`, then the M1 facts and identity tables.

CI didn't surface this (the CI workflow doesn't run a Postgres service; DB-backed tests `pytest.skip` cleanly when the engine can't connect) but it broke local. Worth fixing regardless. Now: 65/65 pass locally.

## Spot-check

Three random settled markets, one per prop type, sampled with `ORDER BY random() LIMIT 1` per `prop_type`:

- `KXNBAPTS-26MAR28CHIMEM-CHIJGIDDEY3-25` Josh Giddey 24.5 points, CHI @ MEM, 2026-03-28, result NO
- `KXNBAREB-26MAR29MIAIND-MIAKWARE7-8` Kel'el Ware 7.5 rebounds, MIA @ IND, 2026-03-29, result NO
- `KXNBAAST-26MAY23NYKCLE-CLEDMITCHELL45-10` Donovan Mitchell 9.5 assists, NYK @ CLE (Eastern Conference Finals), 2026-05-23, result NO

User cross-checked against kalshi.com; player, line, date, teams, and result all match.

## Friction during the run

- **Kalshi 429 on a real run.** Discovered the hard way that the public endpoint will rate-limit a sustained pull. Added the 429-specific retry path before continuing.
- **Branch protection on `main` blocked the README push.** User removed the rule temporarily, pushed, re-enabled. Worth a thought later about whether to keep main fully protected or allow signed commits from the owner directly.
- **`No module named 'app'` on the first CLI attempt.** User was in repo root rather than `backend/`. All `python -m app.x.y` invocations need to start from `backend/`.
- **`zsh: command not found: --min-close-date`.** Multi-line shell command with broken line continuation. Switched to single-line.
- **SSH key not loaded** required `ssh-add ~/.ssh/id_ed25519` before pushing.
- **`m1 only loaded 2022-23 through 2024-25`** initial expectation was that M1 had loaded the current season too. Had to backfill 2025-26 regular season before any Kalshi `game_id` would resolve. After that and the playoffs + Play-In follow-up, FK resolution went 0 -> 10393 -> 19061 -> 19736.
- **Bulk-load summary line read 0 resolved on rerun** existing-row branch only counts NULL -> non-NULL transitions, which made an idempotent rerun look like a no-op. Confirmed via DB query rather than rewriting the summary; counter semantics are correct, just easy to misread.

## What this closes for M2

- Schema (four tables, alembic applied)
- Kalshi REST client routed through `CachedHttpClient`
- Parser mapping Kalshi tickers to `(player, prop_type, game)` tuples
- Bulk historical loader for settled markets, idempotent + re-resolving
- 5-min snapshot job for active markets, with opportunistic settlement writes
- Scheduler wired with both daily ingest and 5-min snapshot
- Four failure-mode tests for the Kalshi path (timeout, 429, malformed JSON, missing field)
- 429 retry-with-backoff in `CachedHttpClient` to handle Kalshi's public rate limit
- `kalshi_player_aliases` populated for all 148 distinct Kalshi-covered players
- `bulk_load` extended to support `Playoffs` and `PlayIn` season types
- Playoffs + Play-In games loaded across four seasons (2022-23 through 2025-26)
- Live historical bulk run verified end-to-end: 19,736 markets, 100% joined to a player + game
- Three spot-checked markets cross-validated against kalshi.com
- Conftest wipe order updated for the M2 schema
- README rewritten and live on public main

What's still pending:
- ADR-3 prose rewrite in Ronnie's voice (drafted in Claude voice, pending hand edit)
- Live scheduler smoke test during an NBA game window (verify `market_snapshots` rows accumulate at 5-min cadence in production-like conditions)

## Quality gates

ruff, black, mypy strict, pytest 65/65 (50 after M2 first half, +6 snapshot, +1 scheduler, +4 failure modes, +3 seed CLI, +1 cache retry). 38 source files.

## Next

M3: baseline model + skeleton backtest harness. First real prediction layer. Define the `predictions` table, write the dumb rolling-average baseline, daily prediction job, replay backtest harness scaffold. Per the roadmap, the baseline being dumb is the point: it exposes pipeline bugs that a complex model would obscure.

---

# M2 start: schema, ADR draft, Kalshi fetcher + parser, bulk loader (pushed 2026-05-31)

Closed the first half of M2. Schema + migration applied, ADR-3 drafted (awaiting Ronnie's voice rewrite), Kalshi fetcher + parser written, bulk loader with alias resolution written and tested end-to-end. Live snapshot job and the manual real-data run still to come.

## Pre-implementation probe of the Kalshi API

Before touching schema, hit `https://api.elections.kalshi.com/trade-api/v2/markets` directly via curl to nail down the ticker structure. Three things confirmed:

1. **Series tickers we need:** `KXNBAPTS` (points), `KXNBAREB` (rebounds), `KXNBAAST` (assists). Found via `/series?category=Sports` filtered to `tags=['Basketball']`. Series for threes (`KXNBA3PT`), PRA, PR, RA exist but are out of scope per PRD §9.
2. **Ticker structure** for an NBA player-prop market: `KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35`. Decomposes as:
   - `KXNBAPTS` — series ticker
   - `26MAY30SASOKC` — event_ticker tail: `YY` + `MMM` + `DD` + 3-char away abbr + 3-char home abbr
   - `SASVWEMBANYAMA1` — player code (team + initial + last name + disambiguation digit)
   - `35` — integer strike suffix
3. **Each market = one binary Yes/No at one strike.** Wembanyama 25+/30+/35+ are three distinct tickers sharing the same `event_ticker`. The `floor_strike` field (34.5) is the authoritative line; `rules_primary` ("If Victor Wembanyama records 35+ Points in the...") is the canonical player name (much more reliable than parsing the ticker's player code).
4. **`?status=settled` returns finalized markets** with `result` ∈ {"yes","no"}, `settlement_value_dollars`, `settlement_ts`. Pagination via `cursor`.

Public read endpoints, no auth needed. No `client_id`, no API key.

## ADR-3 drafted at `docs/adr.md`

Drafted in Claude voice (per ADR-1 precedent: skeleton + Claude draft, Ronnie rewrites later). Covers:

- Schema (four new tables: `markets`, `market_snapshots`, `market_settlements`, `kalshi_player_aliases`).
- Why composite PK `(ticker, quoted_at)` on snapshots.
- Why `markets` is identity-like (in-place updates, FKs nullable until alias resolution succeeds).
- Why no `kalshi_game_aliases` table (M1's `Game.game_date` + team abbreviations make the join clean).
- Why all four price legs stored (yes_bid, yes_ask, no_bid, no_ask not redundant on binary markets).
- Simplest game-day gating: any market with `close_time > now` (not filtered by NBA game windows).
- Alternatives considered: single "over/under" abstraction (rejected, Kalshi serves each strike separately), separate game-alias table (rejected, redundant with M1), mid-price-only snapshots (rejected, cheap to store all four), append-only `markets` (rejected, FK backfill complicates query).
- Open questions: mid vs last for edge calc, the trailing-digit player-code suffix, no historical pre-system snapshots (Kalshi doesn't expose price history), rescheduled games, multi-leg props.

Original draft had a "+1 day arithmetic" mistake on game resolution. Corrected after noticing M1's `Game.game_date` exists as a clean `date` column. Direct equality join, no offset.

## SQLModel tables + Alembic migration

`backend/app/db/tables.py` extended with four classes following M1's conventions:

- **`Market`** (identity-like, PK = `ticker` string). Holds immutable identity (series, event_ticker, prop_type, line, strike_type, open_time, rules_primary) plus resolved FKs (`player_id`, `game_id`), both nullable until alias resolution succeeds. Carries `created_at` + `ingested_at` (with `onupdate=func.now()`). `raw_data` JSONB preserves full Kalshi payload. Four indexes: `close_time` (snapshot job queries), `event_ticker` (group by game), `game_id`, and composite `(player_id, prop_type, game_id)` for the backtest path.
- **`MarketSnapshot`** (fact, composite PK `(ticker, quoted_at)`). Holds all four price legs + `last_price`, `volume`, `volume_24h`, `open_interest`, `liquidity`, `status`, `raw_data`. Composite PK gives the natural btree for `WHERE ticker = ? AND quoted_at <= ? ORDER BY quoted_at DESC`. One extra index on `ingested_at` for the M1-style point-in-time filter.
- **`MarketSettlement`** (fact, PK = `ticker`). One settlement per market. `result`, `settlement_value`, `settled_at`, `ingested_at`, `raw_data`. Index on `settled_at`.
- **`KalshiPlayerAlias`** (mapping, PK = `kalshi_player_name`). The English name extracted from `rules_primary` -> NBA `player_id`. Seeded manually for ~50 covered players (deferred, empty for now).

Migration `db/migrations/versions/124f1a7e317d_m2_kalshi_schema.py` autogenerated, lightly trimmed (autogenerate emitted a redundant `ix_snapshots_ticker_quoted_desc` index that duplicates the composite PK btree; removed). Applied to local Postgres; all 11 tables present.

## `backend/app/data/kalshi.py`

Fetcher + parsers mirroring `nba.py`'s shape.

- **Constants:** `_KALSHI_BASE`, `_SERIES_TO_PROP`, `_MONTH_ABBR`, `_PLAYER_RULES_RE` (`r"^If (.+?) records "`).
- **Parser helpers:** `_parse_kalshi_date` (handles 2000-2079 vs 1980-1999 window), `_parse_event_ticker` (decomposes into series + date + away + home; strict on 13-char tail length), `_parse_player_from_rules` (regex on `rules_primary`), `_parse_iso_utc` (handles trailing `Z`), `_to_float_or_none` (Kalshi's stringified `"0.0100"` -> float).
- **Fetcher:** `fetch_markets_page(client, *, series_ticker, status, limit, cursor, min_close_ts, max_close_ts, ttl)`, single page. `iter_markets(...)` pages through with `max_pages` safety belt.
- **Converters:** `market_row_to_orm` (FKs left NULL, resolution is a separate pass), `market_row_to_snapshot` (defaults `quoted_at` to `updated_time` from API response, falls back to `now()` only if absent. Keeps timing honest against cache hits), `market_row_to_settlement` (returns `None` unless `result` in `{"yes","no"}` and `settlement_ts` present).

Tests in `backend/tests/test_kalshi.py` (18 tests): parser edge cases (bad month abbr, wrong length, hyphenated/apostrophe player names like "Shai Gilgeous-Alexander", "De'Aaron Fox"), unknown series raises, all three prop types map correctly, snapshot uses `updated_time` correctly, snapshot falls back to now when absent, snapshot tolerates missing price fields, settlement gated by result+ts, cache round-trip via `FakeSession`, pagination paginates and stops on empty cursor or empty page.

## `backend/app/data/kalshi_bulk_load.py`

Bulk loader with alias resolution. Same `load_season`-shape from M1: caller commits, the function flushes per FK boundary.

- **Pre-build three lookup maps once per run:** `team_abbr -> team_id`, `kalshi_player_name -> player_id` (from `kalshi_player_aliases`), `(game_date, away_team_id, home_team_id) -> game_id` (from M1's `games`). ~5000 game rows; fits in memory comfortably.
- **For each market:** parse, resolve aliases (dict lookups), if new insert with resolved-or-NULL FKs, if existing backfill NULL FKs whenever the alias table has grown since last run. Settlements queued separately and flushed after `markets` so the FK resolves.
- **Summary counters** (`BulkLoadSummary`): markets_seen, markets_inserted, markets_skipped, markets_errors, settlements_inserted, settlements_skipped, settlements_unsettled, players_resolved, players_unmapped, games_resolved, games_unmapped, plus a `unmapped_player_names: set[str]` so the first 25 unmapped names get logged for manual alias-table seeding.
- **CLI:** `uv run python -m app.data.kalshi_bulk_load --min-close-date 2025-11-01 --max-close-date 2026-05-31`. Default lower bound is 2025-11-01 (Kalshi NBA prop coverage start). Per-run transaction; one rollback on failure.

Tests in `backend/tests/test_kalshi_bulk_load.py` (6 tests):
1. **Round trip with full alias resolution:** seed Team/Player/Game/Alias, mock a settled market, verify markets + settlements rows with both FKs resolved.
2. **Unmapped player -> NULL `player_id`** but row still inserted; `players_unmapped` bumps, name lands in `unmapped_player_names`.
3. **Unknown game (date mismatch) -> NULL `game_id`** but row still inserted; `games_unmapped` bumps.
4. **Idempotent:** second run inserts zero new rows; cache serves all three series_ticker requests; row counts unchanged.
5. **Backfill on rerun:** first run with no alias -> NULL `player_id`. Add alias to DB. Second run -> `players_resolved` bumps and the existing row is updated in place. `session.refresh` confirms the change persisted.
6. **Settlement gating:** unsettled market (no `settlement_ts`, no `result`) -> markets row inserted, settlements row not.

## Patterns reused directly from M1 (verbatim, no per-source forking)

- `CachedHttpClient` with `curl_cffi.requests.Session(impersonate="chrome120")`. Kalshi probably doesn't need TLS fingerprinting, but using the same client keeps the wrapper uniform. No per-source HTTP client swap.
- `FakeSession` from `tests/_fakes.py`. Handler signature `(url, params, headers) -> FakeResponse` worked drop-in for all 24 new Kalshi tests.
- Lookup-map idiom (pre-fetch existing keys into a set, dict membership on the way in). Mirrors M1's `_existing_game_ids` / `_existing_result_game_ids` / `_existing_pgl_keys`.
- Caller-commits / function-flushes orchestration. `load_settled_markets` flushes between markets and settlements; `main()` commits per run.
- Per-batch transaction with rollback on failure. Same shape as `bulk_load.py`'s per-season transaction.
- `BulkLoadSummary` dataclass with end-of-run pretty-print mirroring `SeasonLoadSummary`.
- Argparse CLI with `if __name__ == "__main__": sys.exit(main())`.

## Friction during the run

- **SQLModel forbids `primary_key=True` on `Field` when also passing `sa_column`.** Initial `MarketSnapshot.quoted_at` had both; `RuntimeError` at class definition. Fix: keep `primary_key=True` only inside the `sa_column=Column(...)`. (Ticker is a plain `Field(primary_key=True, foreign_key=...)` and works fine because there's no `sa_column` override.)
- **Autogenerate's redundant index.** Alembic created `ix_snapshots_ticker_quoted_desc` on `(ticker, quoted_at)` even though the composite PK already creates a btree on exactly those columns. Dropped from both the migration file and the model's `__table_args__`.
- **`iter_markets` didn't forward `min_close_ts` / `max_close_ts`.** Initial `kalshi.py` only had them on `fetch_markets_page`, not on the iterator. Bulk-loader tests caught it with a clean `TypeError`. Added the kwargs to `iter_markets` and forwarded.
- **One ADR mistake worth not making again.** First draft said "+1 day arithmetic" for matching Kalshi's date to M1's `Game.event_time`. Forgot M1 stores both `event_time` (next-day midnight UTC, derived) AND `game_date` (real ET date, direct). Use `game_date` for the join. Fixed.
- **Small lint / format fixups.** UP028 (yield-over-for -> yield from), E501 (long error message), import sort, unused `typing.Any` import. All auto-fixable.

## What this closes for M2

- ✅ Schema (four tables, alembic applied)
- ✅ ADR-3 draft in Claude voice (Ronnie's prose pending)
- ✅ Kalshi REST client routed through `CachedHttpClient`
- ✅ Parser mapping Kalshi tickers -> `(player, prop_type, game)` tuples via alias resolution
- ✅ Bulk historical loader for settled markets, idempotent + re-resolving
- ⚠️ Snapshot job (5-min cadence during game days), not yet written
- ⚠️ Failure-mode tests for the Kalshi path (httpx timeout, 429, malformed JSON, missing field), not yet written
- ⚠️ Live bulk run against real Kalshi data, not yet attempted
- ⚠️ `kalshi_player_aliases` seeded for the ~50 covered players, not yet done (manual data-entry task; first bulk_load run will surface unmapped names to know what to add)
- ⚠️ ADR prose in Ronnie's voice, pending

## Quality gates

ruff, black, mypy strict, pytest 50/50 (was 44 after M1 close; +18 kalshi parser, +6 kalshi bulk loader). 31 source files clean.

## Next

Two paths to choose from:

1. **Snapshot job + scheduler wiring** (`kalshi_snapshot.py`). Every 5 min, fetch any market with `close_time > now`, upsert markets, insert snapshots. Add the cron job to `scheduler.py` alongside the daily NBA ingest. Gate by `SCHEDULER_ENABLED` env var as before. Then the four failure-mode tests for the Kalshi path. Then the live bulk run.
2. **ADR prose first.** Code now exists to cite by file path; Ronnie can rewrite ADR-3 in his voice the same way he did ADR-1 and ADR-2.

Either order works. Both must happen before M2 closes.

---

# 🟥 TLS-FINGERPRINT BLOCK BUSTED WITH `curl_cffi` (pushed 2026-05-30)

## 🟥 BIG LEARNING POINT

**`stats.nba.com` was not blocking our IP. It was blocking our TLS fingerprint.** Every Python HTTP library (`httpx`, `requests`, `urllib3`) and even the maintained `nba_api` library shares the same TLS handshake signature, and Akamai's bot manager fingerprints it and silently drops the response. Different IPs don't fix it. Different headers don't fix it. School VPN didn't fix it. TLS fingerprint is the lock; a Chrome-impersonating TLS handshake is the key.

**The one-line fix:** swap `httpx.Client()` for `curl_cffi.requests.Session(impersonate="chrome120")`. Same exact request that hung forever now returns in 0.5–4 seconds.

**Proof:** ran `bulk_load --start 2022-23 --end 2022-23` from the same sandbox IP that had been getting silent-dropped. Full season landed in **23.6 seconds**: 1,230 games, 25,895 player game logs, 30 teams, 539 players. Zero timeouts.

Lesson generalizes: **if a Python HTTP request to a major site silently times out while a browser works fine, suspect TLS fingerprinting before suspecting IP blocking.** Akamai, Cloudflare, PerimeterX all do this now. The free fix is `curl_cffi` (libcurl built against Chrome's BoringSSL). The alternatives (residential proxies, headless browsers) cost money or complexity.

## What changed

- **Added `curl_cffi` to deps.** `uv add curl_cffi`. ~2.5 MiB. Has prebuilt wheels for macOS and Linux (Railway compatible).
- **`backend/app/data/cache.py` rewritten.** Production now uses `curl_cffi.requests.Session(impersonate="chrome120")` instead of `httpx.Client()`. The wrapper's API is unchanged — `cache.get(url, params=, headers=, ttl=)` still returns parsed JSON. The retry-on-timeout loop now catches `curl_cffi.requests.exceptions.Timeout`. Per-call timeout still 90s.
- **`backend/tests/_fakes.py` (new).** Test double: `FakeResponse(status_code, body, raise_on_json=False)` and `FakeSession(handler)` where `handler(url, params, headers) -> FakeResponse`. The wrapper's `client` injection point absorbs either real `curl_cffi.Session` or `FakeSession` at runtime; tests stay in pure Python with no HTTP transport at all.
- **All test files updated.** Replaced `httpx.MockTransport`-based mocks with `FakeSession`. `test_cache.py`, `test_nba.py`, `test_bulk_load.py`, `test_daily.py`, `test_failure_modes.py` all swapped. The handler signature is now `(url, params, headers) -> FakeResponse` instead of `(request) -> httpx.Response`, which is actually cleaner — direct access to dict params instead of `request.url.params`.

## What did NOT change

- The cache wrapper's *behavior* (lookup → fetch on miss → store → return).
- `nba.py` parsers, fetcher signatures, headers, params.
- `bulk_load.py`, `daily.py`, `spot_check.py`.
- `request_cache` table schema.
- Any of the architectural commitments.
- Test count (still 44 passing).

## Friction during the swap

- `mypy` flagged that `impersonate="chrome120"` needs to be a `Literal` type, not a `str`. Inlining the string literal (instead of using a module-level constant) made the inference work.
- `mypy` flagged an unused `# type: ignore` on `HTTPError(response=self)` in the fake; turns out `HTTPError` doesn't need or accept a `response` kwarg in `curl_cffi`. Dropped it.
- One test file had `body = {...}` that needed an explicit `: dict[str, Any]` annotation under strict mypy.

## What this unblocks

M1's last open code item ("Ronnie runs bulk_load against real data") is now actually doable. Whenever you pull these changes and `uv sync`, `python -m app.data.bulk_load --start 2022-23 --end 2024-25` should work end-to-end from your machine. ~70-90 seconds total across three seasons. Then `spot_check --n 3 --seed 42` and eyeball against basketball-reference to close the manual verification.

## Quality gates

ruff, black, mypy strict, pytest 44/44.

---

# Real bulk-load attempt hit live timeout; cache hardened (pushed 2026-05-30)

First real run of `bulk_load --start 2022-23 --end 2024-25` against `stats.nba.com` failed with `httpx.ReadTimeout` partway through the first season's T-level call. The endpoint returns a full season's worth of rows (~25k for player-level, ~2.5k for team-level) and the server can take 30-90 seconds to assemble that response. Our 30s default `httpx` timeout was too tight.

## Changes to `backend/app/data/cache.py`

- **Default timeout 30s → 90s.** Matches `nba_api` library's default; comfortable margin for big season responses.
- **Auto-retry on `httpx.TimeoutException`.** New `max_retries` (default 3) and `retry_backoff_seconds` (default 2.0) constructor params. Exponential backoff: 2s, 4s, 8s. Retry only on timeouts; `HTTPStatusError` (4xx/5xx) and JSON decode errors propagate immediately because they're structural, not transient.
- **`_fetch_with_retry` helper** wraps the network call. Logs at WARNING level on each retry with attempt counter and delay so a hung season is visible in logs.

## Test updates

- `test_cache_propagates_timeout_and_does_not_store` now passes `max_retries=0` so the test doesn't burn through the backoff schedule. Single attempt → propagate → no row written.
- New `test_cache_retries_on_timeout_then_succeeds`: handler raises ReadTimeout twice then returns 200. With `retry_backoff_seconds=0.0` (no real waiting in test), verifies the loop hits the network 3 times and ultimately returns the body.

## What this does NOT add

- Retry on 5xx. The NBA API sometimes returns 5xx briefly; we could retry those too. Skipped for v1 because they're rare in practice and we'd want to be careful not to retry 503s that mean "really overloaded, back off harder." Easy add later.
- Per-call rate limiting (e.g., 600ms sleep between non-cached requests). Probably worth adding once we see actual rate-limit responses in practice. Not preemptively.

## Quality gates

ruff, black, mypy strict, pytest 44/44 (was 43; added retry test).

## Ronnie can now re-run

```
cd backend
uv run python -m app.data.bulk_load --start 2022-23 --end 2024-25
```

If a timeout happens, you'll see WARNING log lines as it retries. If three retries still time out, the season rolls back and the next season starts. Re-running picks up from where it stopped (cache + idempotent upserts).

---

# Failure-mode tests (pushed 2026-05-30)

Closed the last code-side M1 acceptance criterion: the four named ingestion failure modes. Required a small `load_season` hardening to handle malformed rows without crashing the whole season.

## What got written

- **`backend/tests/test_failure_modes.py`** (4 tests, one per failure mode):
  1. **httpx timeout** — `MockTransport` handler raises `httpx.ReadTimeout`. Verify the cache propagates `httpx.TimeoutException` AND the `request_cache` row is NOT written.
  2. **429 rate limit** — handler returns `httpx.Response(429, ...)`. Verify the cache propagates `httpx.HTTPStatusError` (because `raise_for_status()` runs before `_store`), with `exc_info.value.response.status_code == 429`. Row not written.
  3. **Malformed JSON** — handler returns `Response(200, content=b"<html>not json</html>", headers={"content-type": "application/json"})`. Verify `cache.get()` raises a `json.JSONDecodeError` (or `ValueError`, its parent). Row not written.
  4. **Missing field / upstream schema drift** — two-game synthetic P-level response. First row complete; second row has `PLAYER_ID=None`. `load_season` inserts the good row, counts the bad row in `summary.pgls_errors`, completes without raising. Verifies the per-row resilience.

## Hardening of `load_season`

The original PGL loop had `key = (int(row["PLAYER_ID"]), ...)` extraction OUTSIDE the try block. A missing/null `PLAYER_ID` would have killed the whole season. Same issue in the team-identity, player-identity, and team-pair loops.

Now every per-row processing block has a `try/except (KeyError, ValueError, TypeError)` wrap. Caught failures:
- Decrement nothing; the loop just `continue`s.
- For the PGL path, bump `summary.pgls_errors`.
- For the team-pair path, bump `summary.games_errors`.
- For the identity-extraction paths (teams, players), don't double-count because the same upstream row will hit the games / PGL loop and get counted there.

Added two new fields to `SeasonLoadSummary`: `games_errors` and `pgls_errors`. Distinct from `*_skipped` (which means "already existed").

`_format_summary` updated to surface errors only when non-zero, so the happy-path log line stays clean.

## Friction during the run

- First test run failed because the bad P-row crashed in `player_identity_from_row` (called from the Players loop in `load_season`) before the PGL loop got to it. Wrapped that too. Then also wrapped the Teams loop for symmetry.
- Black reformatted three files (whitespace only).
- One `Edit` failed because the file's comment line had changed between my read and edit (Ronnie's hand edit). Re-read and re-edited successfully.

## What this closes

All four named failure modes from `docs/Roadmap.md` M1 acceptance:
- ✅ httpx timeout
- ✅ 429 rate limit
- ✅ Malformed JSON
- ✅ Missing field / upstream schema drift

## M1 status

All M1 code is now written and tested:
- ✅ Schema (six tables, alembic migration applied)
- ✅ ADR skeleton + Claude draft (Ronnie's prose pending)
- ✅ Point-in-time regression test
- ✅ `request_cache` + `CachedHttpClient`
- ✅ `nba_api` LeagueGameLog wrappers + parsers
- ✅ Bulk historical load CLI (`bulk_load.py`)
- ✅ Daily ingestion job (`daily.py` + `scheduler.py`)
- ✅ Spot-check helper (`spot_check.py`)
- ✅ Four specific failure-mode tests
- ⚠️ Manual basketball-reference spot-check (you run the script against real data after a bulk load)
- ⚠️ ADR prose in your voice (skeleton + draft exist in `docs/adr.md`)

43 tests passing. ruff, black, mypy strict green.

## Next

Two things left for M1 to actually close:
1. Kick off `uv run python -m app.data.bulk_load --start 2022-23 --end 2024-25` against your local Postgres. Then `uv run python -m app.data.spot_check --n 3 --seed 42`. Compare the three games against basketball-reference.com.
2. Write the ADR prose in your voice using the skeleton in `docs/adr.md`. The code now exists to cite by file path.

After both, M1 is officially done and we move to M2 (Kalshi).

---

# Spot-check + daily ingestion (pushed 2026-05-30)

Two pieces in one push: the spot-check helper for manual data validation, and the daily APScheduler-driven ingestion job. Plus a small refactor to `load_season` to accept date filters so the daily path reuses the bulk loader.

## Thinking through the daily job design

**Where the daily logic lives.** The orchestration is identical to bulk: fetch T and P rows, upsert in FK order, commit. The only difference is the date filter on the fetch. So instead of duplicating the loop, I extended `load_season` to accept `date_from` and `date_to` (both default `None` = whole season). Daily ingest is a thin wrapper that calls `load_season(..., date_from=yesterday, date_to=yesterday)`. One code path, two callers.

**Season detection.** A daily job running on, say, March 15, 2025 needs to know it's still the 2024-25 season. `current_season(today)` uses a July 1 cutoff: month ≥ 7 → season starts that year, else season started the previous year. Edge-tested for July boundary and century boundary.

**Scheduling cadence and timezone.** Cron at 12:00 UTC daily. That's 8 AM ET, well after the latest possible NBA game has ended (West Coast late starts can run to ~6 AM UTC the next day, so 12:00 UTC is comfortably after). `LeagueGameLog`'s `GAME_DATE` field follows Eastern Time convention, so "yesterday in UTC" at 12:00 UTC reliably equals "yesterday in ET" too. Earlier cron times risk losing late Pacific games.

**APScheduler choice: `AsyncIOScheduler`.** FastAPI runs on an event loop; `AsyncIOScheduler` runs in the same loop and auto-wraps sync jobs in a thread executor. `BackgroundScheduler` (sync) would also work but doesn't share the loop. `BlockingScheduler` is wrong (blocks the process).

**Gating with `SCHEDULER_ENABLED`.** The scheduler is started in FastAPI's lifespan handler, but only if `SCHEDULER_ENABLED=true`. Default off. Otherwise tests and local uvicorn would start firing cron jobs against the dev DB or Anthropic. Production sets the env var on Railway.

**Playoffs.** v1 daily job only runs Regular Season. Playoff games need a separate `season_type="Playoffs"` invocation. For now that's a manual call; revisit when April rolls around. Logged in the daily.py docstring so future-Ronnie doesn't get surprised in late spring.

## Thinking through spot-check design

**Goal: visual diff against basketball-reference.com.** Format matters more than logic. Header line with date, away abbr @ home abbr, away-home score. Then a team block per side: city + name + "(home)" or "(away)" label, then players sorted by points descending (most impactful at top, easy eye scan). Per player: name, pts, reb, ast, MM:SS minutes.

**Format chosen for visual diff:**
```
2024-12-15  BOS @ LAL  112-108
Boston Celtics (away)
  Jayson Tatum             32 pts   6 reb   4 ast  38:00
  ...
Los Angeles Lakers (home)
  LeBron James             28 pts   8 reb   7 ast  36:00
  ...
```
The whitespace columns make stat scanning fast against bbref.

**Random sampling.** Pre-fetch all `game_id`s, then `random.sample`. Seeded for reproducibility (`--seed` flag) so a flaky validation can be re-checked exactly. For our scale (~5k games per season), pulling all IDs into memory is fine; revisit if it ever crosses ~1M.

**Read-only.** No DB writes anywhere. Pure visualization.

**Edge cases tested:** missing `game_id` returns a friendly "not found" line. Empty DB returns an empty list (and `main()` prints a "no games found" message). Minutes formatting handles fractional (`34.5 → "34:30"`) and DNP (`None → "DNP"`).

## What got written

- **`backend/app/data/bulk_load.py`** updated: `load_season` gains optional `date_from`, `date_to`. Existing callers and tests unaffected.
- **`backend/app/data/daily.py`** (new, ~70 lines): `current_season(today)` and `run_daily_ingest(today=None)`. Opens its own session, calls `load_season` with `date_from=date_to=yesterday`, commits.
- **`backend/app/scheduler.py`** (new, ~30 lines): `make_scheduler()` returns an `AsyncIOScheduler` with the daily job at `CronTrigger(hour=12, minute=0, timezone="UTC")` and `misfire_grace_time=3600` so a brief outage doesn't skip a day.
- **`backend/app/main.py`** updated: lifespan handler that starts/stops the scheduler based on `SCHEDULER_ENABLED`. Default off so tests are unaffected.
- **`backend/app/data/spot_check.py`** (new, ~110 lines): `_format_minutes`, `_format_team_block`, `format_game`, `pick_random_game_ids`, `main` with argparse.
- **`backend/tests/test_daily.py`** (5 tests): 4 `current_season` boundary tests + 1 `load_season` test that verifies the date filters reach the request params.
- **`backend/tests/test_spot_check.py`** (5 tests): minutes formatting; happy-path box-score formatting verified by substring match on date, team abbreviations, score, names, and stats; missing-game-id returns friendly message; seeded random sampling is deterministic; empty DB returns empty list.

## Friction during the run

- mypy complained about an unused `# type: ignore[arg-type]` I'd defensively added on `select(Game.game_id)` in spot_check. Turns out mypy didn't need it in this context. Removed.
- Black wanted whitespace tweaks across three files. Applied; no semantic changes.
- The existing `/health` test still passes through the new lifespan because TestClient handles lifespan startup/shutdown and `SCHEDULER_ENABLED` defaults to false (no scheduler is started).

## All quality gates green

ruff, black, mypy strict, pytest 39/39 (10 new + 29 prior).

## What this closes for M1

- ✅ Schema (six tables, alembic applied)
- ✅ ADR skeleton + Claude draft (`docs/adr.md`); Ronnie's prose pending
- ✅ Point-in-time regression test
- ✅ `request_cache` table + `CachedHttpClient` wrapper
- ✅ `nba_api` LeagueGameLog wrappers + parsers
- ✅ Bulk historical load CLI (`bulk_load.py`)
- ✅ Daily ingestion job (`daily.py` + `scheduler.py`)
- ✅ Spot-check helper (`spot_check.py`)
- ⚠️ Specific failure-mode tests (httpx timeout, 429, malformed JSON, missing field) — not yet written; should add before declaring M1 done
- ⚠️ Manual basketball-reference spot-check — needs Ronnie to actually run the script against real data once bulk load has been kicked off

## Next

Two ways to go:
1. Write the four failure-mode tests, then Ronnie runs bulk_load + spot_check against real data, then M1 closes.
2. Move to ADR prose (Ronnie's voice) since all the code now exists to cite.

Recommend (1) first so M1 acceptance can be declared green, then (2) at leisure.

---

# Bulk load CLI written (pushed 2026-05-30)

The orchestration layer that turns `fetch_league_game_log` + parsers into a re-runnable seasonal loader. CLI: `uv run python -m app.data.bulk_load --start 2022-23 --end 2024-25`.

## What got written

- `backend/app/data/bulk_load.py` (~270 lines):
  - `iter_seasons(start, end)` — `"2022-23"` to `"2024-25"` → 3 strings. Raises on bad order.
  - `SeasonLoadSummary` dataclass — per-season counters (rows, new, skipped, elapsed).
  - `_upsert_teams` / `_upsert_players` — PK-lookup upserts. Updates name/city/abbr (or current_name) on existing rows.
  - `_existing_game_ids` / `_existing_result_game_ids` / `_existing_pgl_keys` — set-builders for idempotency checks.
  - `load_season(client, session, *, season, season_type)` — the orchestrator. Five strictly-ordered steps with a flush between each: Teams → Players → Games (collect pending GameResults) → flush → GameResults → flush → PlayerGameLogs → flush.
  - `_format_summary` — pretty per-season log line.
  - `main(argv)` — argparse + season iter + per-season `try/commit/except/rollback`. Returns exit code.

- `backend/tests/test_bulk_load.py` (6 tests):
  - 4 `iter_seasons` tests: range, single, century boundary (2098-99 → 2099-00), end-before-start raises.
  - `test_load_season_round_trip`: synthetic 2-game / 3-team / 3-player LeagueGameLog responses via MockTransport, verify summary counts AND DB state (home/away identified correctly from MATCHUP, scores assigned right, LeBron appears in 2 PlayerGameLog rows).
  - `test_load_season_is_idempotent`: run `load_season` twice with the same handler. Second run: 0 inserts everywhere, all counts in `*_skipped`, and `count[0] == 2` (no second pair of network calls because the cache served them).

## Design choices worth noting

- **Commit granularity is one season per transaction.** Set by `main()`, not inside `load_season`. If 2023-24 fails partway, 2022-23 stays committed and 2024-25 is untouched. Re-runs pick up exactly where they stopped.
- **Two passes over games inside one season.** First pass adds Games and queues GameResults. Then flush so Games exist in the DB. Second pass adds GameResults. The flush boundary is required because `game_results.game_id` is an FK; the same single-flush ordering issue we hit in the schema regression tests applies here too (SQLModel's `foreign_key=` doesn't feed unit-of-work topo sort reliably).
- **Idempotency is enforced by pre-fetching existing keys.** Three `_existing_*` helpers query before inserting. `set` membership check on the way in. Avoids `INSERT ... ON CONFLICT` complexity for v1; simple Python set lookups.
- **`load_season` doesn't commit.** It flushes. `main()` commits per season. This keeps `load_season` testable inside the transaction-rollback fixture: tests can call it and check DB state without polluting the dev DB.
- **The `count[0] == 2` assertion in the idempotency test is the proof.** First run: T call + P call = 2 network requests. Second run: 0 new requests. Cache works end-to-end.
- **Synthetic test data is hand-typed JSON shaped like real LeagueGameLog.** Not a fixture file. Fits inline in the test, makes the test self-documenting.

## Friction during the run

- `dict` without type params at two test signatures tripped mypy strict. Fixed to `dict[str, Any]`.
- Black reformatted the synthetic-JSON-as-Python literal aggressively (every list element on its own line). Verbose but correct; left as is.
- Used `# type: ignore[arg-type]` on the `select().join()` line in `_existing_result_game_ids` — same SQLModel + strict mypy quirk we've seen before with column references.

## All quality gates green

ruff, black, mypy strict, pytest 29/29 (6 new + 23 prior).

## What's next

Two remaining pieces to close M1:

1. **The spot-check helper** (`backend/app/data/spot_check.py`): a CLI that picks N random games from the DB and prints their box scores so they can be eyeballed against basketball-reference.com. Read-only. Was part of the M1 acceptance criteria added in the Roadmap rewrite.
2. **The daily ingestion APScheduler job**: same `fetch_league_game_log` call with `DateFrom=yesterday, DateTo=yesterday`, wired into FastAPI startup. Same idempotent insert paths from `load_season` apply; just a different driver.

After both land, M1's acceptance criteria are all satisfied except the actual basketball-reference manual spot-check, which is a Ronnie-runs-the-script-on-real-data step, not code.

---

# Roadmap and PRD updated to match reality (pushed 2026-05-29)

Two docs had drifted from what we actually built. Brought both back in line.

## `docs/Roadmap.md`

- **Pre-flight checklist:** checked off everything that's done (repo, env, tools), updated the CLAUDE.md location to `docs/CLAUDE.md`, added a `~/.claude/CLAUDE.md` line for the global prefs file. Only McElreath's *Statistical Rethinking* remains unchecked.
- **M0:** added `Status: Done (2026-05-15)` so future readers see it shipped.
- **M1 tasks (big rewrite):**
  - Schema bullet now lists six tables and notes which carry which timestamps.
  - ADR reference path updated to `docs/adr.md` (single file convention, not `docs/decisions/`).
  - Bulk load described as `stats.nba.com/stats/leaguegamelog`, two calls per season (P + T), no `nba_api` library dependency. Calls go through `CachedHttpClient`.
  - Shufinskiy play-by-play explicitly deferred to M7 (with a pointer to the notebook).
  - Daily ingestion described with `DateFrom`/`DateTo` filter using the same code path.
  - Failure-mode tests specified concretely: timeout, 429, malformed JSON, missing field.
  - Spot-check helper added as a task.
- **M1 considerations:** added a paragraph on the franchise/identity decision (rejected for our window). Added the "browser headers required" note about `stats.nba.com`.
- **M1 acceptance:** added the regression-test passing criterion (with file path), the basketball-reference spot-check criterion, and clarified that DB-backed tests skip gracefully when Postgres is unavailable in CI.
- **Top-level cross-refs:** updated mentions of `CLAUDE.md` to `docs/CLAUDE.md` in two places.

## `docs/PRD.md`

- **Top header reference:** updated `CLAUDE.md` path to `docs/CLAUDE.md`; added pointer to `docs/adr.md`.
- **§6.1 Data Ingestion Pipeline acceptance criteria:**
  - Historical box-score line now specifies the `leaguegamelog` endpoint, no library dep, two calls per season (P + T).
  - Shufinskiy line replaced with "deferred to M7" plus a pointer to the notebook.
  - Daily ingestion line uses correct schema column names (`event_time`, `ingested_at` instead of `game_date`).
  - Added the spot-check criterion.
  - Caching layer line now references `request_cache` table by name and explains the TTL semantics.
  - Failure-mode tests specified as the same four concrete cases.

## What was NOT touched

- The three architectural commitments. Still hold.
- The tech stack picks (FastAPI, SQLModel, XGBoost, PyMC, ...).
- Milestone structure M0-M10.
- M2-M10 task lists. We haven't built that work yet; updates land as those milestones happen.
- `docs/CLAUDE.md` (already accurate after last week's trim).
- `docs/adr.md` (skeleton + Claude draft still apply; Ronnie's voice writeup pending).

## Next

Bulk-load CLI: `python -m app.data.bulk_load --start 2022-23 --end 2024-25`. Orchestrates the two `fetch_league_game_log` calls per season, upserts identities first then facts, commits per season for bounded blast radius. Plus the spot-check helper.

---

# nba_api wrappers and parsers (pushed 2026-05-29)

The fetch + parse layer for `LeagueGameLog`. All outbound calls route through `CachedHttpClient`. No `nba_api` library dependency; we hardcode the URL and the magic headers.

## What got written

- `backend/app/data/nba.py` (~230 lines):
  - `_NBA_HEADERS` constant: the 10 browser-like headers `stats.nba.com` requires.
  - `_NBA_STATS_BASE`: `https://stats.nba.com/stats`.
  - `_parse_result_set(body, index=0)`: zips `resultSets[index].headers` with each `rowSet` row into dicts. `strict=True` so an API schema change raises clearly.
  - `_parse_minutes(raw)`: handles `"32:30"` strings, plain floats/ints, None, empty, garbage. Returns `float | None`.
  - `_event_time_from_game_date(s)`: `"YYYY-MM-DD"` → next-day midnight UTC. Conservative approximation; ingested_at is the real protector.
  - `fetch_league_game_log(client, *, season, season_type, player_or_team, date_from, date_to, ttl)`: one function handles bulk historical AND daily incremental (just pass `date_from`/`date_to` for daily).
  - `player_game_log_row_to_orm(row, *, season, season_type)`: P-level row → `PlayerGameLog`. Uses `_int_or_zero` and `_int_or_none` helpers so missing stat fields don't crash.
  - `team_game_log_rows_to_orm(row_a, row_b, *, season, season_type)`: pair of T-level rows → `(Game, GameResult)`. Order-independent; `_split_home_away` figures it out from `MATCHUP` strings (`"LAL vs. BOS"` = home, `"BOS @ LAL"` = away).
  - `player_identity_from_row`, `team_identity_from_row`: identity extractors.

- `backend/tests/test_nba.py` (12 tests):
  - `_parse_result_set` zipping.
  - `_parse_minutes` across all input shapes.
  - `_event_time_from_game_date` correctness incl. year boundary.
  - Player row → ORM full field mapping.
  - Player row → ORM DNP handling (null minutes, missing stats default to 0).
  - Player identity extraction.
  - Team identity from T-level row.
  - `_split_home_away` order-independence + raises on weird MATCHUP.
  - Team rows → (Game, GameResult).
  - Mismatched GAME_ID raises.
  - End-to-end round trip via `MockTransport`: synthetic JSON body, parsed rows match, second call hits cache (no second network call).

## Decisions worth remembering

- **No `nba_api` library dep.** Just hardcoded URL + headers. If `stats.nba.com` ever rotates required headers, `_NBA_HEADERS` is the one place to update.
- **One fetcher, two callers.** Bulk historical and daily incremental both call `fetch_league_game_log`; daily just passes `date_from=yesterday, date_to=yesterday`.
- **Two API calls per season for full M1 ingestion.** P-level for `player_game_logs` + player identity. T-level for `games` + `game_results` + team identity. The bulk loader (next step) orchestrates.
- **T-level rows are the source of truth for `teams`.** P-level rows put the full team display in `TEAM_NAME` (ambiguous to split: "Portland Trail Blazers"). `team_identity_from_row` is documented to expect T-level rows. Bulk loader respects this.
- **`event_time` for fact tables = `(game_date + 1 day) at 00:00 UTC`.** Approximate; documented in `_event_time_from_game_date` why this is safe. `ingested_at` is the actual point-in-time enforcer.
- **`GameResult.status = "final"`** for historical bulk loads. Live/in-progress handling lives in the daily ingestion path later (when we may see games still running at fetch time).
- **Parsers don't touch the DB.** They return ORM objects. Caller adds them to a session, handles upserts, manages commits. Keeps these functions pure and testable.

## Quality gates

ruff, black, mypy strict, pytest 23/23 (12 new + 11 prior). Black reformatted two files (one of mine, one of Ronnie's) for whitespace only, no semantic changes.

## Next

The bulk historical load CLI: `python -m app.data.bulk_load --start 2022-23 --end 2024-25`. Orchestrates the two `fetch_league_game_log` calls per season, upserts identities first, then facts, commits per season for bounded blast radius. Plus the spot-check helper that prints three random games' box scores so Ronnie can eyeball them against basketball-reference.com.

---

# request_cache wrapper written (pushed 2026-05-29)

The Postgres-backed HTTP cache that gates all outbound `nba_api` and Kalshi calls. Required infrastructure before any ingestion code can land.

## What got written

- `backend/app/data/cache.py` — `CachedHttpClient` class (~110 lines). Sync. Wraps httpx, looks up `request_cache` first, fetches and stores on miss/expiry. Plus `_compute_keys(url, params)` helper that produces deterministic `(cache_key, params_hash)` via sha256 of sorted JSON.
- `backend/tests/test_cache.py` — four tests: cache-key determinism (param order doesn't matter), miss writes a row and returns the body, hit returns the body without calling the network, expired row triggers a refetch.

## Key design choices in the code

- **Sync, not async.** Ingestion is sequential loops; async buys nothing and adds complexity. Serving API can stay async; ingestion lives in APScheduler jobs.
- **Cache key is `sha256(url + sorted_params_json)`.** Stable across dict ordering and value types. Stored as the PK on `request_cache`.
- **Caller owns the session.** Wrapper flushes after writes so the row is visible within the session, but does not commit. Lets ingestion code commit at natural batch boundaries (per season, end of script). Lets the test fixture's transaction rollback work unchanged.
- **Only 200 responses cached.** Non-200 raises `httpx.HTTPStatusError`. Not caching errors. Future tweak could cache 404 briefly to avoid re-asking for missing data, not for v1.
- **Injectable httpx client.** Constructor accepts `client: httpx.Client | None` so tests can pass an `httpx.MockTransport`-backed client. `_owns_client` flag tracks whether `close()` should close it (don't close client the caller passed in).
- **Per-call TTL with class default.** `default_ttl` set on the client, override per `get(ttl=...)`. Historical box scores use `None` (never expires). Live snapshots use short timedeltas. Decision made by the caller per endpoint.

## Testing approach

`httpx.MockTransport` with a request counter list. Lets us assert exact request counts (1 on miss, 0 on hit, 2 after expiry). No real network in any test.

The expired-cache test manually sets `row.expires_at` to the past via direct row manipulation rather than mocking `datetime.now()`. Simpler and more honest to the production code path.

## Friction during the run

- Ruff caught a line too long in the `_mock_client` helper signature. Split across lines.
- Ronnie's earlier hand edit to `queries.py` had removed the `# type: ignore[arg-type]` comment on the `desc(PlayerGameLog.event_time)` call. mypy strict flagged it again. Re-added.
- Black reformatted four files Ronnie had hand-touched. Only whitespace, no semantic changes; his casual docstring style and inline comments preserved.

## All quality gates green

ruff, black, mypy strict, pytest 11/11.

## Next

`nba_api` client wrappers in `backend/app/data/nba.py`. Two functions for M1: `fetch_league_game_log(season)` (one call per season, bulk historical) and a daily-scoreboard fetcher (for the daily ingestion job). Both route through `CachedHttpClient`. Parsers convert responses into `Player` / `Team` / `Game` / `PlayerGameLog` rows.

---

# CLAUDE.md restructured (pushed 2026-05-28)

Two cheap wins applied without splitting CLAUDE.md into nested files.

## What changed in `docs/CLAUDE.md`

Trimmed from ~220 lines to ~130. Each section either kept, replaced with a pointer, or removed:

- **Kept (full):** project description, three architectural commitments, Tech stack, Repository layout, Things to flag, Anti-patterns.
- **Compacted:** Data sources reduced to four bullets with pointer to `docs/PRD.md` §4 for detail. Security trimmed to session-relevant rules only.
- **Replaced with pointers:** Scope → PRD.md, V2 roadmap → Roadmap.md.
- **Removed entirely:** GitHub hygiene (one-time setup, mostly done), Notes on this file (obsolete after extraction), the old "Working preferences (Ronnie)" section (moved out, see below).
- **Added:** a "Collaboration" section pointing at `~/.claude/CLAUDE.md` for personal prefs, plus a one-sentence project override (the "pause before changing commitments" rule).
- **Fixed:** Repository layout diagram now includes `db/` subpackage in backend, reflects docs at `docs/` not at root, mentions notebooks dir.

Stale content removed: the "Conventional commits" line under GitHub hygiene conflicted with Ronnie's actual preference (minimal lowercase, captured in auto-memory).

## New file: `~/.claude/CLAUDE.md`

Ronnie's universals (intuition-first, no em dashes, concise, etc.) now live at the user level so they apply to every project he opens in Claude Code, not just this one. 9 lines.

## Why not nested CLAUDE.md per subdirectory?

Considered `backend/CLAUDE.md` and `frontend/CLAUDE.md`. Decided against for now because:
- Most CLAUDE.md content isn't actually frontend-vs-backend (architectural commitments, scope, preferences are all shared).
- The frontend has ~8 lines of stack picks, not enough to justify its own file.
- Backend conventions worth pulling out (point-in-time discipline, keyword-only `as_of`, request_cache discipline) already live in `docs/adr.md` and `notebooks/notebook_notes.md`. Promoting them to a CLAUDE.md would just duplicate.
- Reach for nesting once a subdirectory has ~30+ lines of unique conventions. Probably M5 (XGBoost) or M6 (Bayesian) for the backend. Wait for it.

## Why not `.claude/` for splitting?

`.claude/` is for harness config (settings.json, hooks, subagents, commands), not a place for splitting CLAUDE.md content. Other AI tools (Cursor, Continue) wouldn't see anything stored there anyway.

## Next

Move to ingestion. First milestone in M1's remaining work: `request_cache` wrapper around httpx, then `nba_api` client wrappers using `LeagueGameLog` for bulk historical, then the bulk-load CLI script.

---

# Part 3: point-in-time regression test written (pushed 2026-05-17)

The single most important test in the project. Wrote the query helper and five regression tests that prove the schema's `event_time` / `ingested_at` filter actually keeps future data out of historical queries.

## Decisions made before writing

**Where does the query helper live?** `backend/app/db/queries.py`. Keeps all DB code in one package. Downstream consumers (`backtest/`, `data/`, `api/`) import from here. Considered putting queries under `backtest/` since the backtest harness will be the main consumer, but query helpers are general-purpose enough that the `db` package is the right home.

**How do I isolate DB tests against a real Postgres?** Three patterns considered:

1. Separate test database (`nba_alpha_prop_test`): cleanest isolation but adds CREATE DATABASE bootstrap, second DATABASE_URL env var.
2. Separate schema in the same DB: avoids the second DB but adds schema-juggling code.
3. Transaction rollback against the dev DB: each test runs inside a connection-level transaction that the fixture rolls back. No commits ever land. Zero extra setup.

Went with option 3. The dev DB already has the schema (alembic applied), and SQLAlchemy makes the savepoint pattern clean. The cost is no test concurrency support, fine for v1.

**How does this work in CI?** CI doesn't have Postgres yet. Three options: add Postgres as a GitHub Actions service, mark DB tests with `@pytest.mark.skip_no_db`, or have the fixture detect Postgres availability and skip if unreachable. Chose the third. CI silently skips, local runs the tests. Adding Postgres to CI is a separate task whenever it becomes worth the complexity.

**What test cases?** Five total:

1. Past row visible at `as_of`: returned correctly.
2. Future `event_time`: excluded.
3. Past `event_time` but **future `ingested_at`**: excluded. This is the subtle case. The game happened in the past, but the system didn't know about it yet. A naive implementation that only filters on `event_time` would leak this row, even though point-in-time correctness demands we exclude it.
4. Other players excluded: trivial but proves the player_id filter works alongside the time filters.
5. Positional call raises `TypeError`: the `*,` in the function signature isn't just docstring, it's enforced by Python.

**Plus the rolling-average example from `notebook_notes.md`** (Ronnie's own concrete example: correct avg = 20.0, leaked avg = 25.0). It's the same data as case 1 + 2 above but specifically asserts on the computed average, which is the operational shape of the query we'll use in M3 onward.

**Helper signature.** Keyword-only `as_of`, optional `limit`. `order_by(event_time DESC)` because backtests want most recent first.

## What got written

Three files:

- `backend/app/db/queries.py` — the `query_player_game_logs(*, player_id, as_of, session, limit=None)` helper. Uses SQLAlchemy's `desc()` so mypy is happy (mostly).
- `backend/tests/conftest.py` — two fixtures. `db_engine` (session scope) probes Postgres availability and skips if unreachable. `db_session` (function scope) opens a connection, begins a transaction, yields a Session bound to it, rolls back on teardown.
- `backend/tests/test_point_in_time.py` — six tests (five cases plus the rolling-average example) plus two helpers: `_seed_identity` (inserts a Player, Team, Game so FKs can be satisfied) and `_make_pgl` (builds a PlayerGameLog with defaults).

## Friction hit during execution

**FK ordering inside a single flush.** First run: 5/7 tests failed with `IntegrityError` on `games_away_team_id_fkey` because Game was being inserted before Team within `_seed_identity`'s flush. Expected SQLAlchemy's unit-of-work to topologically sort by FK dependency, but SQLModel's `foreign_key="teams.team_id"` declaration doesn't always feed into that sort. Fix: explicit `session.flush()` between adding Team and adding Game. Inefficient (two flushes instead of one) but correct, and it's test code. Documented the workaround in `_seed_identity`'s docstring so future me doesn't wonder why.

**mypy + SQLModel + SQLAlchemy `desc()`.** mypy sees `PlayerGameLog.event_time` as the runtime `datetime` type (from the Pydantic side) rather than as a SQLAlchemy `InstrumentedAttribute` (which would be a valid argument to `desc()`). The runtime is fine, mypy is wrong, but strict mode flags it. Solution: a single `# type: ignore[arg-type]` comment with an inline explanation. Don't fight the type checker over a known SQLModel quirk.

**An unused `# type: ignore[call-arg]` comment.** I'd added both `misc` and `call-arg` to the ignore list for the positional-call test. mypy only needed `misc`; flagged the unused `call-arg` as an `[unused-ignore]` error. Dropped it.

## Files at the end

```
backend/app/db/queries.py        (new)
backend/tests/conftest.py        (new)
backend/tests/test_point_in_time.py  (new)
```

Quality gates: ruff, black, mypy strict, pytest — all green. 7 tests passing locally (the new 6 plus the existing /health test).

## What this unlocks

- Part 2 (the ADR prose) can now be written against real code, not a sketch. The `Decision` section can cite `query_player_game_logs` by name. The `Consequences` section can point at this test file as the existence proof.
- The ingestion code I'll write next can use this query helper as its read-side counterpart. The keyword-only `as_of` is now a hard contract callers can't accidentally bypass.

---

# M1 migration generated and applied (pushed 2026-05-17)

Schema is live in local Postgres.

## What changed in `db/migrations/env.py`

- Added `sys.path` insertion so env.py can import `app.db` from the `backend/` package.
- Imported `from app.db import tables` for side-effect registration on `SQLModel.metadata`.
- Set `target_metadata = SQLModel.metadata`.
- Added a `_render_item` hook that rewrites `sqlmodel.sql.sqltypes.AutoString` → `sa.String()` in generated migrations. Without it, every migration file would need an explicit `import sqlmodel`. Plain `sa.String` is functionally identical at the DB layer.

## Autogenerate + upgrade

Ran with `DATABASE_URL` inlined to point at the docker-compose Postgres:

```
docker compose up -d postgres
DATABASE_URL=... alembic revision --autogenerate -m "m1 initial schema"
DATABASE_URL=... alembic upgrade head
```

First autogen used AutoString; deleted that file, added `_render_item`, regenerated. The kept file is `db/migrations/versions/50e63e86ec99_m1_initial_schema.py`.

## What's in Postgres now

```
alembic_version | game_results | games | player_game_logs | players | request_cache | teams
```

`player_game_logs` has the expected four indexes (`pkey`, `ix_pgl_ingested`, `ix_pgl_player_event`, `ix_pgl_player_event_ingested`, plus `ix_player_game_logs_game_id` from the per-column `index=True`) and three FKs (to `games`, `players`, `teams`).

## One known limitation worth flagging

`updated_at` on `players` has `onupdate=func.now()` at the SQLAlchemy ORM layer only. Raw SQL `UPDATE` statements won't bump it; only ORM-mediated updates do. Fine for v1 because we don't write raw SQL. If that changes, the fix is a Postgres trigger.

## All quality gates still green

ruff, black, pytest, mypy strict — all pass.

## Next step

Part 3 from the M1 prep parts: the point-in-time regression test. Write a query helper (`app/db/queries.py` or similar) with keyword-only `as_of`, then the pytest with past/future rows. Once that exists, Part 2 (ADR prose) can be written against real code instead of a sketch.

---

# SQLModel scaffolding (pushed 2026-05-17)

Wrote the data layer. Three files under `backend/app/db/`:

- `tables.py` — six SQLModel classes matching the locked schema: `Player`, `Team`, `Game`, `GameResult`, `PlayerGameLog`, `RequestCache`. All timestamp columns use `DateTime(timezone=True)` with server-side `func.now()` defaults. `raw_data` columns use Postgres JSONB. Composite indexes on `player_game_logs`: `(player_id, event_time)`, `(player_id, event_time, ingested_at)`, `(ingested_at)`.
- `engine.py` — lazy engine accessor + FastAPI `get_session` dependency. Reads `DATABASE_URL` from env via `python-dotenv` so a local `.env` just works. Normalizes `postgres://` → `postgresql+psycopg://` for Railway/Heroku-era URLs.
- `__init__.py` — re-exports.

Naming choice: SQLModel classes live under `backend/app/db/`, not `backend/app/models/`. CLAUDE.md reserves `app/models/` for ML models (XGBoost, PyMC). Keeping SQL "models" under `db/` avoids the name overload.

Added `python-dotenv` as an explicit dep. Updated `.env.example` with `DATABASE_URL=postgresql+psycopg://nba:nba@localhost:5432/nba_alpha_prop` matching docker-compose defaults.

All quality gates pass: ruff, black, pytest (the existing /health test still works because the engine is lazy and `main.py` doesn't import `db`), mypy strict.

## Notable schema choices to eyeball

- `game_id` is `str`. NBA IDs are zero-padded; storing as int would lose leading zeros.
- `minutes` is `float | None`. DNP players get `null` or `0`. No separate status column on `player_game_logs` yet.
- `status` column exists on `game_results` ("final" / "in_progress" / "postponed"). Open question in the ADR is what values it actually takes.
- `raw_data` is non-null at the DB level (defaults to empty dict).
- FK on `player_game_logs.team_id` points at `teams.team_id` directly so trades within a season are handled per-game.

## Next step

Wire `alembic env.py` to `SQLModel.metadata`, run `alembic revision --autogenerate -m "m1 initial schema"`, review the generated migration line-by-line, apply against local Postgres.

---

# Notes cleanup and ADR scaffolded (pushed 2026-05-17)

Two artifacts updated/created to reflect the locked M1 schema decisions.

## `notebooks/notebook_notes.md` (rewritten in place)

- Removed all `franchises` / `franchise_identities` references. `teams` is a single table keyed by NBA official team IDs.
- Promoted `game_results` from a "Refinement" subsection to a real M1 table.
- Marked the `play_by_play_events` section as explicitly "Deferred to M7" rather than "Optional."
- Updated all schema columns: `franchise_id` → `team_id` in `games`, `player_game_logs`, and the relationship sketch.
- Updated Part 1 status from "drafted as a starting hypothesis" to "decisions locked, ready for SQLModel + Alembic."
- Updated the ADR Prep section's bullet list to remove franchise questions and clarify `game_results`-in-M1 reasoning.
- Added a practical note: bulk loading uses `LeagueGameLog`, not per-game `BoxScoreTraditionalV2`.

The shufinskiy exploration content is preserved unchanged; it's still useful M7 context.

## `docs/adr.md` (new file)

Structure:
1. **Skeleton** for Ronnie to fill in his own voice. Per-section prompts only, no prose. Calls out which alternatives the Alternatives Considered section should cover.
2. **Claude draft** below, clearly labeled "casual voice, reference only." Six tables, the timestamp split, the keyword-only `as_of`, the `request_cache`, the `LeagueGameLog` choice, the JSONB `raw_data` columns. Honest Negative consequences. Alternatives Considered covers six rejected options including the eoinamoore rewind discussion and the franchise split.

The file is `docs/adr.md` (singular), tracked in git, will collect future ADRs under the same header pattern.

---

# M1 schema decisions locked (pushed 2026-05-17)

Three open decisions from the prep audit are settled.

1. **Simple `teams` table.** No `franchises`/`franchise_identities` split. Ronnie pushed back on my reversal: the split's only real value is rename history, which doesn't apply in our 2022-23+ window. I had overstated the "conceptual cleanness" case. Walked back, simple `teams` it is.
2. **`game_results` separate from `games`.** Append-only so stat corrections (NBA revises lines) don't overwrite history.
3. **`play_by_play_events` deferred to M7.** Keeps M1 tight; only needed for lineup features later.

## Final M1 schema (six tables)

- `players`
- `teams`
- `games`
- `game_results`
- `player_game_logs`
- `request_cache`

Fact tables (`games`, `game_results`, `player_game_logs`) carry `event_time` + `ingested_at`. Identity tables (`players`, `teams`) carry `created_at` only.

## Next implementation order

1. SQLModel classes in `backend/app/models/`.
2. `backend/app/db.py` engine/session driven by `DATABASE_URL`.
3. `alembic revision --autogenerate` then review line-by-line.
4. Apply against local Postgres.
5. Then Part 3 (regression test), then Part 2 (ADR).

---

# M1 source rewind considered, rejected (pushed 2026-05-17)

A separate Claude session pitched switching the bulk historical load from `nba_api` to the eoinamoore Kaggle dataset. After review with Ronnie, decided not to rewind.

## Pitch (summarized)

Three claimed wins for switching:
1. PBP isn't needed for v1.
2. `TeamHistories.csv` solves franchise identity over time.
3. Bulk CSV is faster than nba_api (claimed 12 min/season due to per-game API calls).

## What actually held up

1. PBP-not-needed: true, but Ronnie's notebook already established this. Not new info.
2. Franchise-solved: irrelevant for our 2022-23+ window. All major renames are pre-2014. A stable `teams` table with NBA's official IDs covers everything. (Ronnie caught me reversing position on this from the prior turn.)
3. Bulk speed: overstated. The 12-min math assumed per-game `BoxScoreTraditionalV2` calls. The right tool is `LeagueGameLog`, which returns one full season in ~2 calls. Bulk load is fast with the right endpoint.

Strip out the inflated wins and the case collapses against the cost of taking a Kaggle dependency (single-maintainer nightly ETL) on the foundation of the data layer.

## Decision

Stay with `nba_api` for both bulk and incremental. No doc churn. Schema, regression test spec, ADR skeleton, notebook work all intact.

## One thing to carry forward

When scaffolding nba_api wrappers in M1 implementation, use **`LeagueGameLog`** (and `LeagueDashPlayerStats` if needed) for bulk loading. Per-game `BoxScoreTraditionalV2` is the wrong tool for bulk and was the assumption behind the rewind pitch's speed argument.

## Honesty note

I called the franchise split "conceptually clean" in the prior turn's M1 prep audit, after we'd already agreed in the planning turn that it was moot for our data window. That inconsistency is what made the eoinamoore pitch sound stronger than it was. Ronnie flagged it.

---

# M1 prep audit (pushed 2026-05-16, after Ronnie's notebook work)

Reviewed `notebooks/explore_shuf.ipynb` and `notebooks/notebook_notes.md`. Ronnie did most of the M1 prep work himself.

## Progress against the four prep parts

- **Part 4 (shufinskiy inspection):** done. Key finding: shufinskiy is raw play-by-play, not box scores. Resolved the data-source split: `nba_api` for `player_game_logs`, shufinskiy for play-by-play (deferred).
- **Part 1 (schema design):** ~65%. Plain-English sketch is solid (five M1 tables plus three optional refinements, indexes, query pattern). Missing: three open decisions, SQLModel classes, Alembic migration.
- **Part 3 (regression test):** ~40%. Spec is fully written (function signature with keyword-only `as_of`, past/future row example, expected outputs). Code not yet written; depends on schema.
- **Part 2 (ADR):** ~50%. Skeleton is complete (Context/Decision/Consequences/Alternatives Considered/Open Questions, 11 decisions enumerated, 4 alternatives rejected with reasoning). Prose not yet written; correctly deferred until schema + test exist.

## Three open schema decisions Ronnie owes himself

1. Simple `teams` vs `franchises`+`franchise_identities`? My take: do the split. Two tables instead of one, conceptually clean even without renames in 2022-23+.
2. `game_results` separate from `games` in M1? My take: yes. Stat corrections happen; append-only results without overwriting history.
3. `play_by_play_events` loaded in M1 or deferred? My take: defer to M7 lineup work. Keeps M1 tight.

## Re-evaluation of my earlier feedback

Two updates based on the notebook work:

- **Team identity (Q2):** Ronnie pointed out renames are pre-2014. True for that risk. But the franchise/identity split is still conceptually clean even without renames. Reversing my earlier "drop it" position. Recommend the split.
- **shufinskiy as a box-score source:** my original M1 summary implied shufinskiy fed `player_game_logs`. Ronnie's notebook proved it doesn't. The corrected source split (nba_api for box scores, shufinskiy for PBP) is now reflected upstream in the notes.

## Division of labor going into M1 implementation

Ronnie owns: schema decisions, SQLModel review, regression test (or pair-write), the ADR.

I own: `request_cache` mechanics, `nba_api` wrapper code, bulk historical load script, daily ingestion job, httpx retry/backoff, four failure-mode tests, the spot-check helper.

---

# M1 planning (pushed 2026-05-16, pre-implementation)

Discussion only, no code yet. M0 deploy work is happening in a separate session in parallel.

## What M1 actually delivers

- Four tables in Postgres: `players`, `teams`, `games`, `player_game_logs`. Each row gets `event_time` (when the fact was true) and `ingested_at` (when we wrote it down). This timestamp split is the schema-level expression of commitment #1.
- ADR in `docs/decisions/` explaining the schema and the point-in-time invariant.
- Alembic migrations creating that schema.
- One-time bulk load of historical box scores/player game logs via `nba_api`, 2022-23 season onward, protected by the request cache.
- One-time bulk load of historical play-by-play from `github.com/shufinskiy/nba_data`, 2022-23 season onward. This dataset is raw events, not summary box scores.
- Daily ingestion job using `nba_api` for in-season box scores and player game logs.
- A `request_cache` table in Postgres so any `nba_api` call is dedup'd before hitting the network. Protects us from rate-limit bans.
- Tests: happy path plus at least one failure mode for each ingestion source.

## My feedback on the milestone

Three tweaks I'd make:

1. **Specific failure-mode tests, not vague ones.** Roadmap says "at least one failure mode." I'd write four small ones: httpx timeout, 429 rate-limit, malformed JSON, missing field (upstream schema drift). Each catches a different bug class.
2. **Team identity is not as stable as the roadmap implies.** Franchise IDs persist but names/cities change (SEA → OKC, NJN → BKN, NOH → NOP). If we store team identity by current name, historical joins go sideways. Store franchise_id plus a snapshot of name/city as of `event_time`. Five-minute decision now, multi-hour bug later if missed.
3. **Spot-check the bulk load.** Once `nba_api` box-score data is loaded, pick three real games and compare player lines against basketball-reference.com. Cheap sanity check, catches whole-dataset bugs early. Not in the roadmap; I'd add it.

Things I'd leave alone:
- `request_cache` table in Postgres. Right call at this scale; avoids dragging Redis in.
- Defaulting to 2022-23 onward. Don't need more history until M5.
- SQLModel over raw SQLAlchemy. The Pydantic + FastAPI integration is worth it.

## What you (Ronnie) should personally do or deeply understand

1. **Schema design.** Sketch on paper before any Alembic. The `event_time` / `ingested_at` split is the most consequential decision in M1. Review every column before migration code lands.
2. **The ADR.** Write it in your own voice. It's a recruiter-visible artifact. I can scaffold; the reasoning should be yours.
3. **The point-in-time regression test.** The test that deliberately tries to leak future data and asserts the leak fails. This is the technical proof of commitment #1. Write it yourself.
4. **Read the shufinskiy README and query raw rows.** Don't trust any "data is loaded" claim until you've personally inspected the shape. Ten minutes of poking saves hours later. The important finding is that shufinskiy gives raw play-by-play events, so it should not be treated as the direct source for `player_game_logs`.

Things you can safely delegate to me: Alembic migration boilerplate, the daily-job harness, the cache table mechanics, httpx retry/backoff, ingestion CLI scaffolding.

## Branch points the roadmap calls out (and my defaults)

- **How far back to load?** Stick with 2022-23. Backfill later if M5 needs it.
- **Normalize via FK or denormalize?** Normalize. Postgres is fast enough; we're nowhere near the scale where denorm matters.
- **SQLModel vs raw SQLAlchemy?** SQLModel. Locked in CLAUDE.md anyway.

## Open questions before we start M1

1. Are we OK adding a `docs/decisions/` directory with ADRs as the convention going forward? (Roadmap implies yes.)
2. Schema-first or code-first? Suggest: draft the schema in markdown in the ADR, then write SQLModel classes to match, then `alembic revision --autogenerate` and review the generated migration before applying.
3. How do we want to run the daily job locally vs in production? APScheduler in-process when the FastAPI app runs is the CLAUDE.md default; that means the daily job only runs while the Railway service is alive. Fine for v1; flag it.

---

# Build process notes (M0)

Personal notes for Ronnie. Walks through every command run and every file written during M0, with reasoning. Gitignored, not part of the public artifact.

---

## Pre-flight: reading the spec

**Commands**

```
Read CLAUDE.md
Read docs/ROADMAP.md   # failed: file does not exist
Read docs/PRD.md       # failed: file does not exist
ls -la && ls -la docs/
Read Roadmap.md, PRD.md, README.md, .gitignore, .env  (parallel)
```

**Why**

The user asked me to read three files in order. The first read worked, the next two failed because the docs aren't under `docs/`, they're at the repo root with different casing. Ran a directory listing to recover. Then read the four docs plus `.gitignore` and `.env` so I could give an accurate answer to "what's set up vs what's missing." Reading in parallel because none of them depend on each other.

**Outputs that mattered**

- The four planning docs are at repo root and listed in `.gitignore`. That decision was confirmed mid-conversation: README carries the public artifact story; the planning docs stay local.
- `.env` already had a real Anthropic key. `.env.example` did not exist yet.
- No `LICENSE`, no GitHub remote info available locally, no backend or frontend dirs.

---

## Phase 1: LICENSE, .env.example, README placeholder

**Files written**

- `.env.example`: documents the env shape so anyone cloning the repo knows which vars to set. Just `ANTHROPIC_API_KEY=` for now; will grow as later milestones add `DATABASE_URL`, `DISCORD_WEBHOOK_URL`, etc.
- `LICENSE`: standard MIT text with copyright "nba prop", year 2026. M0 acceptance and CLAUDE.md require MIT.
- `README.md`: short under-construction placeholder. Three small sections: one-paragraph project description (using "forecasting and market comparison" framing per CLAUDE.md, not "betting"), a status note pointing at the milestone-driven plan, and a license note. M10 will rewrite this with screenshots and demo links.

**Commands**

```
Write .env.example, LICENSE, README.md  (parallel)
git status && git diff --stat
git add .env.example LICENSE README.md
git commit -m "..."
git log --oneline -5
```

**Why**

These three files are the smallest, most independent units of work in M0. Doing them first gets the legal and shape-documentation pieces out of the way before touching code. `.env.example` and `LICENSE` are new so they were untracked; `README.md` was modified.

---

## Phase 2: Backend skeleton

**Tooling check**

```
uv --version && python3 --version && ls backend
```

Confirmed `uv 0.11.14`, system Python 3.14.4 available (uv will manage the project's specific version), no `backend/` directory yet.

**Project init and dependencies**

```
mkdir -p backend/app/{api,data,models,backtest,alerts} backend/tests db
cd backend && uv init --bare --python 3.11

uv add fastapi 'uvicorn[standard]' sqlmodel alembic httpx apscheduler anthropic 'psycopg[binary]'
uv add --dev pytest ruff black mypy httpx
```

`mkdir` first so the directory tree matches CLAUDE.md's target layout exactly: `app/api`, `app/data`, `app/models`, `app/backtest`, `app/alerts`, `tests/`, plus a `db/` for the upcoming migrations dir. The `--bare` flag on `uv init` skips the auto-generated `hello.py` and README, since we want our own structure.

`requires-python = ">=3.11"` in `pyproject.toml`. Not pinning to a specific version because future ML libraries (PyMC, XGBoost) might lag on the bleeding-edge Python. The lockfile resolved against 3.14 since that's what was available.

Runtime dependencies are exactly the ones CLAUDE.md locks in: FastAPI for the web layer, uvicorn for the ASGI server, SQLModel for the ORM, Alembic for migrations, httpx for outbound HTTP, APScheduler for in-process scheduling, anthropic for the LLM SDK, psycopg for Postgres. Dev dependencies are the four CLAUDE.md tooling picks plus `httpx` again because FastAPI's `TestClient` depends on it (it's already a runtime dep, but listing it in dev makes the intent visible).

**Source files written**

- `app/__init__.py` plus `app/{api,data,models,backtest,alerts}/__init__.py`: empty marker files so each is a proper Python package. Required for clean imports across the codebase.
- `app/main.py`: minimal FastAPI app with one `/health` endpoint that returns `{"status": "ok"}`. M0 acceptance asks only for a reachable health check.
- `tests/__init__.py`: empty.
- `tests/test_health.py`: uses FastAPI's `TestClient` to assert `/health` returns 200 and the right body. Smallest possible regression test, but it locks in the contract.
- `pyproject.toml`: extended with `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.black]`, `[tool.mypy]`, `[tool.pytest.ini_options]` sections.
  - Ruff: `line-length = 100`, target py311, lint rules `E F I B UP` (pycodestyle errors, pyflakes, import sorting, bugbear, pyupgrade). Per-file ignore so tests can use bare `assert` without bugbear complaining about side effects.
  - Black: same line length, py311 target.
  - Mypy: strict mode, `ignore_missing_imports = true` because some libs (`pbpstats`, `nbainjuries` later) won't have stubs. Strict catches the things we want; `ignore_missing_imports` keeps it bearable.
  - Pytest: `testpaths = ["tests"]` and `pythonpath = ["."]` so `from app.main import app` works without installing the package or fighting with `sys.path`.

**Local verification (parallel)**

```
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy app tests
```

All three passed first try. Running them in parallel because they don't share state.

**Alembic scaffolding**

```
uv run alembic init ../db/migrations
ls db/migrations && grep -n "script_location|sqlalchemy.url" backend/alembic.ini
Read db/migrations/env.py
Edit alembic.ini  # blank out the placeholder sqlalchemy.url
Edit db/migrations/env.py  # read DATABASE_URL from env, override config
```

CLAUDE.md target layout puts `db/migrations/` at the repo root, not under `backend/`. Running alembic init from `backend/` with `../db/migrations` as the path means alembic.ini lands in `backend/` (cwd) but the migrations dir lands at the repo root. Alembic resolves the relative path against the `.ini` file's location with `%(here)s/../db/migrations`, which works portably.

The two edits keep secrets out of files. The placeholder `sqlalchemy.url = driver://user:pass@localhost/dbname` was wiped to blank. The `env.py` was patched to read `DATABASE_URL` from the environment and call `config.set_main_option("sqlalchemy.url", database_url)` if present. Now the actual connection string only ever lives in env vars (local `.env` or Railway env vars in production).

**Smoke test against running server**

```
uv run uvicorn app.main:app --port 8765 --log-level warning   # background
until curl -sf http://127.0.0.1:8765/health ...; do sleep 1; done
kill the background uvicorn
```

Pytest already covered the endpoint via `TestClient`, but I wanted to confirm uvicorn actually boots and serves on a port (a different failure surface than `TestClient`). Used a non-default port (8765) to avoid colliding with anything else. The `until` loop polls so we don't have to guess startup time. Got 200 with the right body, killed the process.

**Commit**

```
git status
git add -A --dry-run | head -30
git add -A && git commit -m "..."
```

The dry-run was a safety check: I wanted to confirm `.venv/` and caches were excluded by `.gitignore` before adding everything. `uv.lock` is included on purpose, just like `package-lock.json` is on the frontend side; lockfiles must be committed for reproducible installs.

---

## Phase 3: Dockerfile + docker-compose

**Files written**

- `backend/Dockerfile`: `python:3.14-slim` base (matches the version uv resolved against locally, so the lockfile installs cleanly). Pulls `uv` from `ghcr.io/astral-sh/uv:latest` (single COPY, no shell install). Copies `pyproject.toml` and `uv.lock` first, then runs `uv sync --frozen --no-dev --no-install-project`. The two-step copy is the standard layer-caching trick: if only source files change, the dep layer stays cached. After deps, copies `backend/app`, `backend/alembic.ini`, and `db/migrations` into the image. `EXPOSE 8000`, then `CMD` runs uvicorn binding 0.0.0.0. Build context is the repo root because we need to include `db/migrations/` which lives outside `backend/`.
- `docker-compose.yml`: two services. `postgres` uses `postgres:17` with a named volume (`postgres_data`) so data survives `docker compose down`, and a healthcheck so the backend service can wait for `pg_isready`. Credentials default to `nba/nba/nba_alpha_prop` but are overridable with env vars (`${POSTGRES_USER:-nba}` syntax). `backend` service builds from the Dockerfile with the repo root as context, sets `DATABASE_URL` to the `postgresql+psycopg://...` URL pointing at the `postgres` service hostname, exposes port 8000, and depends on Postgres being healthy.

The non-secret defaults are intentional. CLAUDE.md's "no defaults in code" rule is about app code, not local infra config. Local Postgres credentials are not secrets, and the override-via-env pattern means a developer who wants something different can set it without editing the file.

**Verification**

```
docker info >/dev/null 2>&1 && echo running || echo NOT running
docker compose config --quiet && echo "compose syntax OK"
```

Docker Desktop wasn't running, so the full `docker compose up -d` test still needs to happen. `docker compose config` validates the YAML and resolves env-var substitution without needing the daemon, so we got at least syntax confirmation.

**Commit**

```
git add backend/Dockerfile docker-compose.yml && git commit -m "..."
```

---

## Phase 4: Frontend skeleton

**Tooling check + scaffold**

```
node --version && npm --version
npx --yes create-next-app@latest frontend \
  --typescript --tailwind --app --eslint \
  --import-alias "@/*" --no-src-dir --use-npm --skip-install --yes
```

Node 25.9.0, npm 11.12.1. `create-next-app` with explicit flags so it runs without prompting: TypeScript on, Tailwind on, App Router, ESLint, default `@/*` alias for imports, no `src/` directory (CLAUDE.md target layout has `app/` directly under `frontend/`), npm as the package manager, and `--skip-install` so we don't pay the install time twice (we install in the next step alongside TanStack Query).

Generated Next.js 16.2.6 with React 19 and Tailwind 4. The template added `frontend/AGENTS.md` and `frontend/CLAUDE.md`. Both are auto-generated stubs. Kept them: AGENTS.md has a useful warning that Next 16 has breaking changes from training data and points future agents at `node_modules/next/dist/docs/` for current docs. The frontend `CLAUDE.md` just delegates to AGENTS.md and is gitignored at the root level anyway.

**Install dependencies including TanStack Query**

```
cd frontend && npm install @tanstack/react-query
```

One install for everything (the deps from create-next-app's `package.json` plus TanStack Query). Faster than running `npm install` twice.

**Inspect templates and check Next 16 patterns**

```
ls frontend/app
Read layout.tsx, page.tsx, globals.css   (parallel)
ls node_modules/next/dist/docs
find docs -name "*provider*"
```

Wanted to confirm before writing client-side code that the Next 16 layout/provider pattern is unchanged from what I knew. The bundled docs confirmed the standard Server-Component-layout-imports-Client-Component-provider pattern still applies.

**Files written / replaced**

- `app/providers.tsx`: tiny client component (`"use client"`) wrapping children in `QueryClientProvider`. Uses `useState(() => new QueryClient())` so the QueryClient is created once per browser session, not per render. This is the recommended TanStack pattern for App Router; without `useState`, every re-render would create a new client and lose cache.
- `app/layout.tsx`: replaced the create-next-app version. Stripped the Geist font setup (not needed for a placeholder, less code to read), updated `metadata` to `nba_alpha_prop`, wrapped `{children}` in `<Providers>`. The provider lives inside `<body>` so it surrounds all rendered pages.
- `app/page.tsx`: replaced with a small "Under construction" page. Three lines of JSX: a heading, a paragraph, centered with Tailwind. M0 acceptance just wants something rendering at the URL; this is the minimum.

**Verification**

```
npm run lint
npm run dev -- --port 3456   # background
until curl -sf http://127.0.0.1:3456/ ...; do sleep 2; done
grep "nba_alpha_prop" /tmp/page.html
kill the dev server
```

ESLint passed silently. Next.js dev compiles on demand, so a clean lint doesn't actually prove the page renders. Started dev on a non-default port (3456), polled until ready, fetched `/`, confirmed the page contains the new title, killed the process.

**Commit (and amend)**

The first commit message was the verbose conventional-commit style I'd used so far. Ronnie pushed back: he wants minimal lowercase one-liners. Amended to "frontend skeleton implemented", saved that as feedback memory, applied to all later commits.

---

## Phase 5: Pre-commit + CI

**Files written**

- `.pre-commit-config.yaml`: uses `local` hooks rather than upstream pre-commit repos. Reason: mypy needs the actual project deps to type-check correctly, and `additional_dependencies` in the upstream-repo style is fragile (you'd have to keep it in sync with `pyproject.toml`). Local hooks just shell out to `uv run --directory backend ...` so they use the real venv. Three hooks: ruff check (with `--fix`), black, mypy. All scoped to `^backend/` files.
- `.github/workflows/ci.yml`: two jobs.
  - `backend`: checks out, sets up uv with caching, `uv sync --frozen`, then ruff check, `black --check`, mypy, pytest.
  - `frontend`: checks out, sets up Node 22 with npm caching keyed on `frontend/package-lock.json`, `npm ci`, lint, build.

  Triggers on push-to-main and PRs against main. Two separate jobs (not steps in one job) so they run in parallel and a failure in one doesn't mask the other.

**Why `pass_filenames: false` and explicit args on black**

The first run of `uvx pre-commit run --all-files` failed: pre-commit was passing repo-relative file paths like `backend/app/data/__init__.py` to black, but the entry was `uv run --directory backend black`, which switches cwd to `backend/`. Black couldn't find `backend/app/data/__init__.py` from inside `backend/`. Fix: add `pass_filenames: false` and `args: [app, tests]` so black always runs against `app` and `tests` from inside `backend/`, regardless of which file changed. Same pattern mypy was already using. Slightly less efficient than per-file (full-tree format every run) but correct.

**Verification**

```
uv run --directory backend black --check app tests
uvx pre-commit run --all-files   # first try failed on black, second succeeded
uvx pre-commit install
```

`pre-commit install` writes `.git/hooks/pre-commit` so the hooks fire automatically on `git commit`.

**Commit**

```
git add .pre-commit-config.yaml .github/workflows/ci.yml
git commit -m "pre-commit hooks and ci workflow added"
```

The pre-commit hook fired on this commit but skipped all three checks because the files staged weren't Python.

---

## Cleanup: rewriting the verbose commits

Three earlier commits still had verbose conventional-commit messages. Rewrote them via interactive rebase with a sequence-editor that injects `exec git commit --amend -m "..."` lines after each target pick:

```
SEQ=$(mktemp)
cat > "$SEQ" <<'EOF'
#!/bin/sh
sed -i.bak '
/^pick b39fe2e/a\
exec git commit --amend -m "license, env example, and readme placeholder added"
/^pick 94e4c08/a\
exec git commit --amend -m "backend skeleton implemented"
/^pick 1edbf20/a\
exec git commit --amend -m "dockerfile and docker-compose added"
' "$1"
EOF
chmod +x "$SEQ"
PRE_COMMIT_ALLOW_NO_CONFIG=1 GIT_SEQUENCE_EDITOR="$SEQ" git rebase -i HEAD~5
```

The first attempt failed because pre-commit fired on each amend, but at the historical commit being amended, `.pre-commit-config.yaml` didn't exist yet (it gets added in a later commit). Pre-commit refuses to run with no config. `PRE_COMMIT_ALLOW_NO_CONFIG=1` tells pre-commit to no-op when config is missing. Not bypassing any actual lint check; just tolerating the historical absence of config.

The rebase succeeded, all five M0 commits now use the minimal one-line style, and `pytest` still passes against the rewritten history (sanity check).

---

## Commit history at end of M0 (local, not yet pushed)

```
9cc495e pre-commit hooks and ci workflow added
8d04773 frontend skeleton implemented
0b2b79e dockerfile and docker-compose added
08b84e3 backend skeleton implemented
e910168 license, env example, and readme placeholder added
971b0ca basics            (pre-existing)
cc38c98 first             (pre-existing)
a6bd787 Initial commit    (pre-existing)
```

(SHAs shifted again after the rebase; current HEAD SHAs are visible via `git log --oneline`.)

---

## Memory saved across sessions

Three memory files in `~/.claude/projects/.../memory/`:

- `doc-layout.md` (project): the four planning docs live at repo root and are gitignored on purpose; README is the public artifact.
- `reviewer-md-purpose.md` (project): `Reviewer.md` is for a separate Claude review session, not project documentation.
- `feedback-commit-style.md` (feedback): minimal lowercase one-liners, no conventional-commit prefix, no body, no Co-Authored-By trailer.

Each linked from `MEMORY.md`. These persist across future sessions in this repo so I won't have to re-derive them.

---

## What's verified locally vs still needs you

Verified:
- `uv run uvicorn app.main:app --reload` boots, `/health` returns 200
- `npm run dev` boots, `/` renders the placeholder
- Pytest, ruff, black, mypy all green
- ESLint green
- Pre-commit hooks fire on commit
- `docker compose config` valid

Not yet verified (Phase 6, mostly your turn):
- `docker compose up -d` actually brings up Postgres (Docker Desktop wasn't running)
- Push to GitHub
- CI runs and passes on a real PR
- Railway deploy + URL
- Vercel deploy + URL
- Branch protection on `main`


# Old Read Me

# nba_alpha_prop
A full NBA player prop forecasting system. XGBoost feature prediction with a hierarchical bayesian model. compares posterior distributions to live prediction market prices, surfaces pos EV edges, tracks its own calibration. uses LLM to classify injury news into structured prior updates. 


## Live urls 👍

  Frontend: https://nba-alpha-prop.vercel.app/
  Backend health: https://gregarious-friendship-production-b0f6.up.railway.app/health

