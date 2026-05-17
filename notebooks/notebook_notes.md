# M1 Prep Notes: shufinskiy Data, Schema Design, Test, ADR

These notes are for Milestone 1 prep. The goal is not to implement schema yet.
The goal is to understand the raw data shape before designing tables or writing
Alembic.

Status of the four prep items:

- Part 4, shufinskiy inspection: done locally in the notebook.
- Part 1, schema design: drafted as a starting hypothesis, not final.
- Part 3, point-in-time regression test: documented as the required test shape,
  not implemented yet.
- Part 2, ADR: documented as the structure and decisions to explain, not written
  as the final recruiter-visible ADR yet.

Recommended order stays:

```text
4 -> 1 -> 3 -> 2
```

Do not write Alembic before the schema sketch is reviewed. Do not write the
final ADR before the schema and test exist.

## 4. shufinskiy Data Inspection

### Main Finding From shufinskiy

The local file inspected was:

```text
notebooks/nbastats_2024.csv
```

This is the 2024 regular season `nbastats` export from
`github.com/shufinskiy/nba_data`.

Important finding:

```text
shufinskiy nbastats is raw play-by-play event data, not player game logs.
```

That resolves the source split:

- Use `nba_api` for historical and current box scores/player game logs.
- Use shufinskiy for historical play-by-play.
- Cache every `nba_api` request in Postgres because `stats.nba.com` is
  rate-limited.

This keeps M1 focused on `player_game_logs` from real box-score/player-log
sources. Shufinskiy remains useful later for lineup, possession, and on-court
features.

## What The shufinskiy File Looks Like

Observed shape:

- Rows: 574,360
- Columns: 34
- Unique games: 1,230
- Score-bearing rows: 155,778
- Unique teams found in player event slots: 30
- Unique player IDs found in event slots: 1,343

The row count is the giveaway. One NBA regular season has about 1,230 games. A
player-game-log dataset would usually have roughly 20-30k rows for one season.
This file has over 500k rows because each row is an event: shot, rebound, foul,
substitution, period start, period end, replay, etc.

## shufinskiy Columns

```text
GAME_ID
EVENTNUM
EVENTMSGTYPE
EVENTMSGACTIONTYPE
PERIOD
WCTIMESTRING
PCTIMESTRING
HOMEDESCRIPTION
NEUTRALDESCRIPTION
VISITORDESCRIPTION
SCORE
SCOREMARGIN
PERSON1TYPE
PLAYER1_ID
PLAYER1_NAME
PLAYER1_TEAM_ID
PLAYER1_TEAM_CITY
PLAYER1_TEAM_NICKNAME
PLAYER1_TEAM_ABBREVIATION
PERSON2TYPE
PLAYER2_ID
PLAYER2_NAME
PLAYER2_TEAM_ID
PLAYER2_TEAM_CITY
PLAYER2_TEAM_NICKNAME
PLAYER2_TEAM_ABBREVIATION
PERSON3TYPE
PLAYER3_ID
PLAYER3_NAME
PLAYER3_TEAM_ID
PLAYER3_TEAM_CITY
PLAYER3_TEAM_NICKNAME
PLAYER3_TEAM_ABBREVIATION
VIDEO_AVAILABLE_FLAG
```

## Date And Time

This file does not have `GAME_DATE`.

Time-related fields:

- `WCTIMESTRING`: wall-clock string, for example `7:11 PM`
- `PCTIMESTRING`: period-clock time remaining, for example `12:00`, `11:43`,
  `0:00`
- `NEUTRALDESCRIPTION`: sometimes embeds a timezone label, for example
  `Start of 1st Period (7:11 PM EST)`

Schema implication: shufinskiy alone is not enough to produce an exact
`scheduled_tip_time_utc`. For M1 game metadata, use `nba_api` schedule/box-score
data or another source that includes game dates.

## Game Identity

- `GAME_ID` is populated on every row.
- `EVENTNUM` identifies the event sequence within the game.
- Likely natural key for raw play-by-play events: `(GAME_ID, EVENTNUM)`, but
  validate it during ingestion. The local file has two duplicate rows by this
  key, so the loader should either deduplicate exact duplicates or include a
  raw-row hash/version field.

That natural key belongs on a raw `play_by_play_events` table, not on
`player_game_logs`.

## Team Identity

Team identity appears inside player participant slots:

- `PLAYER1_TEAM_ID`, `PLAYER1_TEAM_CITY`, `PLAYER1_TEAM_NICKNAME`,
  `PLAYER1_TEAM_ABBREVIATION`
- Same pattern for `PLAYER2_*`
- Same pattern for `PLAYER3_*`

This means a play-by-play row does not have one simple `TEAM_ID`. The team is
attached to the event participant.

Schema implication: if raw play-by-play is stored, either preserve these slots
as raw columns or normalize event participants into a child table later.

## Player Identity

Player identity appears in up to three participant slots:

- `PLAYER1_ID`, `PLAYER1_NAME`
- `PLAYER2_ID`, `PLAYER2_NAME`
- `PLAYER3_ID`, `PLAYER3_NAME`

Rows without a real participant use ID `0` and blank name/team fields. Do not
assume `PLAYER1_ID` is always a real player.

## What This File Does Not Have

This file does not directly contain:

- `PTS`
- `REB`
- `AST`
- `MIN`
- `GAME_DATE`

Some stats could be derived from events, but minutes played and DNP handling
would require substitution/on-court logic or a separate box-score source. For
M1, use `nba_api` for player-game facts.

## M1 Schema Design, Plain English

The M1 schema should separate three ideas:

1. Stable identities: players and franchises.
2. Game-level facts: scheduled games and final results.
3. Player-game facts: one row per player per game, with stats and timing fields.

The point-in-time commitment lives in the timestamp split:

- `event_time`: when the basketball fact happened.
- `ingested_at`: when this system learned or recorded the fact.

A backtest pretending to run at time `as_of` can only use rows where:

```sql
event_time < :as_of
AND ingested_at <= :as_of
```

Both checks matter. A game could have happened yesterday, but if the system did
not ingest it until today, then a backtest set to yesterday should not see it.

## Core Tables To Sketch Before Alembic

### `players`

Stable player identity.

Likely columns:

- `player_id`: NBA official player ID, primary key
- `current_name`
- `created_at`
- `updated_at`

V1 limitation: do not track temporal player name changes yet. Document this in
the ADR.

### `franchises`

Stable team/franchise identity.

Likely columns:

- `franchise_id`: internal primary key
- `nba_team_id`: NBA official team ID, unique
- `created_at`

This table represents the stable entity. It should not change just because a
team changes city, name, or abbreviation.

### `franchise_identities`

Historical team names and abbreviations.

Likely columns:

- `franchise_identity_id`
- `franchise_id`
- `valid_from`
- `valid_to`
- `city`
- `name`
- `abbreviation`

This handles cases like Seattle/Oklahoma City without rewriting historical
data.

### `games`

One row per NBA game.

Likely columns:

- `game_id`: NBA official game ID, primary key
- `season`
- `season_type`
- `game_date`
- `scheduled_tip_time_utc`, nullable if unknown
- `home_franchise_id`
- `away_franchise_id`
- `event_time`
- `ingested_at`
- `created_at`

Keep player stats out of this table.

### `game_results`

Final results, stored separately so corrections can be appended instead of
overwriting game metadata.

Likely columns:

- `game_result_id`
- `game_id`
- `home_score`
- `away_score`
- `status`
- `event_time`
- `ingested_at`
- `raw_data`

If the NBA revises a result, insert a new observed result with a later
`ingested_at`.

### `player_game_logs`

The main M1 fact table, sourced from `nba_api`, not shufinskiy.

Likely columns:

- `player_game_log_id`: surrogate primary key
- `player_id`
- `game_id`
- `franchise_id`: team the player played for in this game
- `season`
- `season_type`
- `event_time`
- `ingested_at`
- `minutes`
- `points`
- `rebounds`
- `offensive_rebounds`
- `defensive_rebounds`
- `assists`
- `steals`
- `blocks`
- `turnovers`
- `personal_fouls`
- `field_goals_made`
- `field_goals_attempted`
- `three_pointers_made`
- `three_pointers_attempted`
- `free_throws_made`
- `free_throws_attempted`
- `plus_minus`
- `raw_data`

Use a surrogate primary key for easier references later. Add a uniqueness rule
that reflects the ingestion/versioning decision. For maximum point-in-time
rigor, allow append-only versions when a stat correction arrives.

### `request_cache`

Postgres-backed cache for upstream API calls.

Likely columns:

- `cache_key`
- `url`
- `params_hash`
- `response_body`
- `status_code`
- `fetched_at`
- `expires_at`

This is what makes `nba_api` safe for historical bulk loading.

## Optional Table For shufinskiy

### `play_by_play_events`

This is where shufinskiy belongs.

Likely columns:

- `game_id`
- `event_num`
- `period`
- `wall_clock_time`
- `game_clock`
- `event_msg_type`
- `event_action_type`
- `home_description`
- `visitor_description`
- `neutral_description`
- `score`
- `score_margin`
- player slot fields, or later a normalized event participants table
- `raw_data`
- `event_time`
- `ingested_at`

Likely natural key:

```text
(game_id, event_num)
```

For M1, this can be documented as planned or loaded as a raw table. It should
not be confused with `player_game_logs`. The ingestion code should still check
for duplicate `(game_id, event_num)` rows before enforcing a unique constraint.

## Critical Indexes

For `player_game_logs`:

```text
(player_id, event_time)
(player_id, event_time, ingested_at)
(game_id)
(ingested_at)
```

The backtest query pattern:

```sql
SELECT *
FROM player_game_logs
WHERE player_id = :player_id
  AND event_time < :as_of
  AND ingested_at <= :as_of
ORDER BY event_time DESC
LIMIT :window_size;
```

That query is the database-level expression of the point-in-time commitment.

## Recommended Sketch

Draw these boxes first:

```text
franchises -> franchise_identities
franchises -> games.home_franchise_id
franchises -> games.away_franchise_id
players -> player_game_logs
games -> player_game_logs
games -> game_results
games -> play_by_play_events
```

Then write this beside `player_game_logs`:

```text
event_time < as_of
ingested_at <= as_of
```

Everything in M1 should protect that invariant.

## 3. Point-In-Time Regression Test

This is the most important test in the project because it proves commitment #1:
historical predictions cannot silently train on future data.

The pattern:

1. Insert one past game log that should be visible at a simulated `as_of`.
2. Insert one future game log that should not be visible.
3. Run the query or rolling-average function.
4. Assert the result only uses the past row.
5. Assert the function cannot be called without an explicit `as_of`.

Plain-English example:

```text
Player 1, Game A:
event_time = 2024-01-01
ingested_at = 2024-01-02
points = 20

Player 1, Game B:
event_time = 2024-01-15
ingested_at = 2024-01-16
points = 30

Query as_of = 2024-01-10

Expected rolling average = 20.0
Incorrect leaked average = 25.0
```

The query helper should require `as_of` as a keyword-only argument:

```python
def query_player_game_logs(
    *,
    player_id: int,
    as_of: datetime,
    session: Session,
) -> list[PlayerGameLog]:
    ...
```

The `*,` matters. It forces callers to pass `as_of` explicitly:

```python
query_player_game_logs(player_id=1, as_of=as_of, session=session)
```

No default `as_of`. No hidden "latest data" path for historical queries.

The core filter:

```python
.filter(PlayerGameLog.player_id == player_id)
.filter(PlayerGameLog.event_time < as_of)
.filter(PlayerGameLog.ingested_at <= as_of)
```

The regression test should fail loudly if a future row leaks in. This test
belongs near the first query helper or baseline model, before the backtest
harness gets complicated.

## 2. ADR Prep

The ADR should be written last, after the schema sketch is reviewed and the
point-in-time regression test exists. If it is written too early, it will read
like a wish list instead of a record of real decisions.

Working title:

```text
ADR-001: M1 Schema Design for Point-in-Time Correctness
```

The ADR should explain these decisions in your own voice:

- Why point-in-time correctness is a schema-level commitment, not just query
  discipline.
- Why fact tables use both `event_time` and `ingested_at`.
- Why historical team identity uses `franchises` plus
  `franchise_identities`.
- Why game results are separate from immutable game metadata.
- Why `player_game_logs` uses `nba_api`, not shufinskiy.
- Why shufinskiy belongs in raw play-by-play storage.
- Why temporal player names are out of scope for v1.
- Why historical query helpers require explicit `as_of`.

Suggested ADR structure:

```markdown
# ADR-001: M1 Schema Design for Point-in-Time Correctness

## Status
Accepted, [date]

## Context
- This project must support honest backtests.
- Backtests can only use facts known before the simulated prediction time.
- Mutable rows, current-state joins, and careless "latest value" queries can
  silently leak future data.
- shufinskiy provides raw play-by-play, not player-game box scores, so M1 uses
  nba_api for player-game facts and shufinskiy for event-level data.

## Decision
- Use `event_time` and `ingested_at` on fact tables.
- Use `franchises` plus `franchise_identities` for team naming over time.
- Keep `games` metadata separate from append-only `game_results`.
- Store player-game facts in `player_game_logs`, sourced from nba_api.
- Store raw source rows in `raw_data`.
- Require `as_of` in historical query helpers.

## Consequences

### Positive
- Backtest queries have a clear point-in-time filter.
- Re-ingestion and stat corrections can be represented without overwriting
  history.
- Team name changes do not corrupt historical joins.
- The query API forces developers to think about time.

### Negative
- More tables than a naive schema.
- Some queries require joins.
- Storage is larger because raw source rows and append-only versions are kept.
- Raw SQL can still bypass helper functions, so review and tests matter.

## Alternatives Considered

### Mutable game rows
Rejected because final scores or corrected stats could overwrite prior observed
state and make old backtests impossible to reproduce honestly.

### Denormalized team names on player_game_logs
Rejected as the only source of truth because it makes franchise history harder
to reason about. It may still be useful as a performance denormalization later.

### Full event sourcing for every table
Rejected for v1 because it adds too much complexity before the baseline
pipeline exists.

### Deriving player_game_logs from shufinskiy play-by-play
Rejected for M1 because shufinskiy is raw event data. Deriving points/rebounds/
assists/minutes from events would require a transformation pipeline and
substitution logic. nba_api box-score/player-log endpoints are the direct source
for M1.

## Open Questions
- Whether player name changes need temporal tracking.
- Whether raw play-by-play is loaded in M1 or deferred until lineup features.
- Whether to add prediction versioning in M3.
- Whether to denormalize team/player labels after profiling.
```

The most important ADR section is `Alternatives Considered`. That is where the
engineering judgment shows up.
