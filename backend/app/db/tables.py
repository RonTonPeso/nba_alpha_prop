"""SQLModel table definitions

Six tables: players, teams, games, game_results, player_game_logs,
request_cache.

Fact tables (games, game_results, player_game_logs) carry both event_time
(when the fact was true in the world) and ingested_at (when this system
recorded it). Backtest queries must filter on both:

    WHERE event_time < :as_of AND ingested_at <= :as_of

Identity tables (players, teams) carry created_at only.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Index
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
