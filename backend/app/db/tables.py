"""SQLModel table definitions

M1 tables: players, teams, games, game_results, player_game_logs,
request_cache.

M2 tables: markets, market_snapshots, market_settlements,
kalshi_player_aliases. See ADR-3 in docs/adr.md.

M3 table: predictions. One row per (player, game, prop, model version).
prediction_time is when the forecast claims to have been made.
ingested_at is when this system stored the row.

Fact tables carry event_time (when the fact was true in the world)
and ingested_at (when this system recorded it). Box scores and game
results also carry available_at. For a bulk load that is 12:00 UTC
on the day after game_date. For a live fetch it equals ingested_at.

Feature reads of player_game_logs filter on:

    WHERE event_time < :as_of AND available_at <= :as_of

Market quotes stay on both original clocks:

    WHERE quoted_at <= :as_of AND ingested_at <= :as_of

For market_snapshots the event_time analog is quoted_at; for
market_settlements it's settled_at.

Identity tables (players, teams, markets) carry created_at only.
Mapping tables (kalshi_player_aliases) carry created_at only.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel

# Identity tables


class Player(SQLModel, table=True):
    __tablename__ = "players"

    # NBA's official player ID. Stable across seasons.
    player_id: int = Field(primary_key=True)
    current_name: str
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )


class Team(SQLModel, table=True):
    __tablename__ = "teams"

    # NBA's official team ID.
    team_id: int = Field(primary_key=True)
    name: str  # like da "Lakers"
    city: str  # "Los Angeles"
    abbreviation: str  # "LAL"
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )


# Fact tables


class Game(SQLModel, table=True):
    __tablename__ = "games"

    # NBA game IDs are zero-padded strings like "0022400001".
    game_id: str = Field(primary_key=True)
    season: str  # "2024-25"
    season_type: str  # "Regular Season", "Playoffs", etc.
    game_date: date
    scheduled_tip_time_utc: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    home_team_id: int = Field(foreign_key="teams.team_id")
    away_team_id: int = Field(foreign_key="teams.team_id")

    # event_time for a Game is its tip time. Set by ingestion.
    event_time: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    ingested_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )


class GameResult(SQLModel, table=True):
    """Append-only. New observations (corrections, finalizations) add rows."""

    __tablename__ = "game_results"

    game_result_id: int | None = Field(default=None, primary_key=True)
    game_id: str = Field(foreign_key="games.game_id", index=True)
    home_score: int
    away_score: int
    status: str  # "final", "in_progress", "postponed", etc.

    # event_time is when this result became true, i.e., game end.
    event_time: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    ingested_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )
    # 12:00 UTC the day after game_date for a bulk load. The fetch time
    # for a live load. Feature reads use this, not ingested_at.
    available_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )


class PlayerGameLog(SQLModel, table=True):
    """One row per player per game. Append-only for stat corrections."""

    __tablename__ = "player_game_logs"
    __table_args__ = (
        Index("ix_pgl_player_event", "player_id", "event_time"),
        Index("ix_pgl_player_event_ingested", "player_id", "event_time", "ingested_at"),
        Index("ix_pgl_player_event_available", "player_id", "event_time", "available_at"),
        Index("ix_pgl_ingested", "ingested_at"),
    )

    player_game_log_id: int | None = Field(default=None, primary_key=True)

    player_id: int = Field(foreign_key="players.player_id")
    game_id: str = Field(foreign_key="games.game_id", index=True)
    team_id: int = Field(foreign_key="teams.team_id")

    season: str
    season_type: str

    # event_time is the time the box score became a fact, like, game end.
    event_time: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    ingested_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )
    # 12:00 UTC the day after game_date for a bulk load. The fetch time
    # for a live load. Feature reads use this, not ingested_at.
    available_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Stats. This is nullable.
    minutes: float | None = None
    points: int = 0
    rebounds: int = 0
    offensive_rebounds: int = 0
    defensive_rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    personal_fouls: int = 0
    field_goals_made: int = 0
    field_goals_attempted: int = 0
    three_pointers_made: int = 0
    three_pointers_attempted: int = 0
    free_throws_made: int = 0
    free_throws_attempted: int = 0
    plus_minus: int | None = None

    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )


# M2: Kalshi market data


class Market(SQLModel, table=True):
    """One row per Kalshi market ticker. Identity-like (in-place updates).

    Holds the immutable market identity (series, event_ticker, prop_type,
    line, strike_type, open_time, rules_primary) plus resolved FKs
    (player_id, game_id), both nullable until alias resolution succeeds.

    close_time can shift if Kalshi triggers an early close, so the row is
    updated in place. raw_data JSONB preserves the latest observed full
    market object so we can re-resolve aliases later.
    """

    __tablename__ = "markets"
    __table_args__ = (
        Index("ix_markets_close_time", "close_time"),
        Index("ix_markets_event_ticker", "event_ticker"),
        Index("ix_markets_player_prop_game", "player_id", "prop_type", "game_id"),
        Index("ix_markets_game_id", "game_id"),
    )

    # Kalshi market ticker, e.g. "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35".
    ticker: str = Field(primary_key=True)

    # Kalshi series ticker, e.g. "KXNBAPTS", "KXNBAREB", "KXNBAAST".
    series_ticker: str

    # Kalshi event ticker (a game's group), e.g. "KXNBAPTS-26MAY30SASOKC".
    event_ticker: str

    # Derived from series_ticker: "points" | "rebounds" | "assists".
    prop_type: str

    # The market line. From Kalshi's floor_strike, e.g. 34.5 for a "35+" market.
    line: float

    # Kalshi's strike_type, e.g. "structured", "greater", "less".
    strike_type: str

    # Trading window.
    open_time: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    close_time: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Human-readable fields from Kalshi.
    title: str  # "Victor Wembanyama: 35+ points"
    rules_primary: str  # Full settlement rule text. Used for alias resolution.

    # Raw Kalshi name surfaces for alias resolution. Populated at parse time.
    kalshi_player_name: str  # "Victor Wembanyama"
    kalshi_event_date: date  # 2026-05-30
    kalshi_home_abbr: str  # "OKC"
    kalshi_away_abbr: str  # "SAS"

    # Resolved FKs. Nullable until aliases match; backfillable later.
    player_id: int | None = Field(default=None, foreign_key="players.player_id")
    game_id: str | None = Field(default=None, foreign_key="games.game_id")

    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )
    ingested_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )

    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )


class MarketSnapshot(SQLModel, table=True):
    """One row per (ticker, quoted_at). Composite PK gives idempotency.

    quoted_at is the event_time analog: when the price was real on Kalshi.
    All four bid/ask legs are stored; on a binary market yes_ask + no_ask
    sums near 1.00 in liquid markets but bid sides do not.

    Price fields are nullable because a market with no liquidity can be
    missing the field entirely in the API response.
    """

    __tablename__ = "market_snapshots"
    # The composite PK (ticker, quoted_at) provides the btree index for the
    # backtest "latest snapshot at or before T" query path. No extra index
    # needed on those two columns.
    __table_args__ = (Index("ix_snapshots_ingested", "ingested_at"),)

    ticker: str = Field(primary_key=True, foreign_key="markets.ticker")
    quoted_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), primary_key=True, nullable=False),
    )
    ingested_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )

    # Order book top-of-book. All in dollars (Kalshi binary in [0, 1]).
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None

    last_price: float | None = None
    volume: float | None = None  # Cumulative since market open.
    volume_24h: float | None = None
    open_interest: float | None = None
    liquidity: float | None = None

    status: str  # "active", "finalized", etc. as seen at quoted_at.

    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )


class MarketSettlement(SQLModel, table=True):
    """One row per settled market. PK = ticker (one settlement per market).

    settled_at is the event_time analog: when the market resolved on Kalshi.
    """

    __tablename__ = "market_settlements"
    __table_args__ = (Index("ix_settlements_settled_at", "settled_at"),)

    ticker: str = Field(primary_key=True, foreign_key="markets.ticker")

    result: str  # "yes" | "no"
    settlement_value: float  # Dollar value of the Yes contract at settlement.

    settled_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    ingested_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )

    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )


class KalshiPlayerAlias(SQLModel, table=True):
    """Kalshi English player name -> NBA player_id mapping.

    PK is the kalshi_player_name (e.g. "Victor Wembanyama"), extracted from
    rules_primary at parse time. Seeded semi-manually for the ~50 covered
    players. Unresolved names log to load summary and can be added later.
    """

    __tablename__ = "kalshi_player_aliases"

    kalshi_player_name: str = Field(primary_key=True)
    player_id: int = Field(foreign_key="players.player_id", index=True)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )


# M3: stored forecasts


class Prediction(SQLModel, table=True):
    """One forecast of a counting stat for one player in one game.

    The row is the distribution summary, not a pick against a Kalshi line.
    Lines are joined at scoring time so one forecast can be checked against
    every strike Kalshi listed.

    Same (player, game, prop, model_version) is written once. A later run
    skips. A changed model is a new model_version, not an overwrite.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "game_id",
            "prop_type",
            "model_version",
            name="uq_predictions_player_game_prop_version",
        ),
        Index("ix_predictions_player_time", "player_id", "prediction_time"),
        Index("ix_predictions_game", "game_id"),
    )

    prediction_id: int | None = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="players.player_id")
    game_id: str = Field(foreign_key="games.game_id")
    prop_type: str  # "points" | "rebounds" | "assists"
    model_version: str

    prediction_time: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    ingested_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )

    # Normal approximation of the baseline. Not a claim that the stat is normal.
    mean: float
    std: float
    quantile_10: float
    quantile_50: float
    quantile_90: float
    n_games: int
    low_confidence: bool

    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )


# Infrastructure
class RequestCache(SQLModel, table=True):
    """Postgres-backed cache for upstream API calls.

    cache_key is a deterministic hash of (url, params) computed by the
    caller. expires_at is nullable; null means never expires (useful for
    historical data that's settled).
    """

    __tablename__ = "request_cache"

    cache_key: str = Field(primary_key=True)
    url: str
    params_hash: str
    response_body: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    status_code: int
    fetched_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )
    expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
