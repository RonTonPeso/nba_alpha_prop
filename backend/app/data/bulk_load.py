"""Bulk historical loader for NBA box scores via ``LeagueGameLog``.

Iterates a season range, makes two ``LeagueGameLog`` calls per season
(``PlayerOrTeam=T`` for game metadata + scores + team identity,
``PlayerOrTeam=P`` for player-game stats + player identity), upserts
into Postgres in FK order, commits per season.

Idempotent because: ``request_cache`` means we don't hit network
 again for same calls. Identity upserts look up by primary key.
``games`` insert skips if there is a``game_id`` that already exists
 similarly for ``game_results`` and ``player_game_logs``

Run:
    uv run python -m app.data.bulk_load --start 2022-23 --end 2024-25
"""

import argparse
import logging
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlmodel import Session, select

from app.data.cache import CachedHttpClient
from app.data.nba import (
    fetch_league_game_log,
    player_game_log_row_to_orm,
    player_identity_from_row,
    team_game_log_rows_to_orm,
    team_identity_from_row,
)
from app.db.engine import get_engine
from app.db.tables import Game, GameResult, Player, PlayerGameLog, Team

logger = logging.getLogger(__name__)


def iter_seasons(start: str, end: str) -> Iterator[str]:
    """``'2022-23'`` to ``'2024-25'`` (inclusive) → 3 seasons.

    Raises ValueError if end is before start.
    """
    start_year = int(start.split("-")[0])
    end_year = int(end.split("-")[0])
    if end_year < start_year:
        raise ValueError(f"end season {end!r} is before start {start!r}")
    for year in range(start_year, end_year + 1):
        yield f"{year}-{(year + 1) % 100:02d}"


@dataclass
class SeasonLoadSummary:
    season: str
    season_type: str
    t_rows: int = 0
    p_rows: int = 0
    teams_total: int = 0
    teams_new: int = 0
    players_total: int = 0
    players_new: int = 0
    games_inserted: int = 0
    games_skipped: int = 0  # already existed
    games_errors: int = 0  # couldn't parse (missing field, bad MATCHUP, etc.)
    results_inserted: int = 0
    results_skipped: int = 0
    pgls_inserted: int = 0
    pgls_skipped: int = 0  # already existed
    pgls_errors: int = 0  # couldn't parse (missing field, bad type, etc.)
    elapsed_seconds: float = 0.0


def _upsert_teams(session: Session, teams: list[Team]) -> tuple[int, int]:
    """Upsert. Returns ``(total, new)``. Updates name/city/abbr on existing rows."""
    new_count = 0
    for team in teams:
        existing = session.get(Team, team.team_id)
        if existing is None:
            session.add(team)
            new_count += 1
        else:
            existing.name = team.name
            existing.city = team.city
            existing.abbreviation = team.abbreviation
    return len(teams), new_count


def _upsert_players(session: Session, players: list[Player]) -> tuple[int, int]:
    """Upsert. Returns ``(total, new)``. Updates current_name on existing rows."""
    new_count = 0
    for player in players:
        existing = session.get(Player, player.player_id)
        if existing is None:
            session.add(player)
            new_count += 1
        else:
            existing.current_name = player.current_name
    return len(players), new_count


def _existing_game_ids(session: Session, *, season: str, season_type: str) -> set[str]:
    games = session.exec(
        select(Game).where(Game.season == season, Game.season_type == season_type)
    ).all()
    return {g.game_id for g in games}


def _existing_result_game_ids(session: Session, *, season: str, season_type: str) -> set[str]:
    """Set of ``game_id``s that already have at least one ``GameResult`` row."""
    rows = session.exec(
        select(GameResult)
        .join(Game, Game.game_id == GameResult.game_id)  # type: ignore[arg-type]
        .where(Game.season == season, Game.season_type == season_type)
    ).all()
    return {r.game_id for r in rows}


def _existing_pgl_keys(session: Session, *, season: str, season_type: str) -> set[tuple[int, str]]:
    pgls = session.exec(
        select(PlayerGameLog).where(
            PlayerGameLog.season == season,
            PlayerGameLog.season_type == season_type,
        )
    ).all()
    return {(p.player_id, p.game_id) for p in pgls}


def load_season(
    client: CachedHttpClient,
    session: Session,
    *,
    season: str,
    season_type: str = "Regular Season",
    date_from: date | None = None,
    date_to: date | None = None,
) -> SeasonLoadSummary:
    """Load one season into the DB. Caller commits.

    ``date_from`` / ``date_to`` narrow the LeagueGameLog window. Bulk
    historical leaves them None (whole season). The daily ingestion job
    sets both to yesterday for a one-day pull.

    Order of operations is dictated by FK dependencies:
    teams → players → games → game_results → player_game_logs.
    Each step flushes before the next so FKs resolve.
    """
    logger.info("Loading %s %s", season, season_type)
    start_time = time.monotonic()
    summary = SeasonLoadSummary(season=season, season_type=season_type)

    # Fetch (both cached after first run).
    t_rows = fetch_league_game_log(
        client,
        season=season,
        season_type=season_type,
        player_or_team="T",
        date_from=date_from,
        date_to=date_to,
    )
    p_rows = fetch_league_game_log(
        client,
        season=season,
        season_type=season_type,
        player_or_team="P",
        date_from=date_from,
        date_to=date_to,
    )
    summary.t_rows = len(t_rows)
    summary.p_rows = len(p_rows)

    # Teams. Skip malformed rows here; the games loop below counts the
    # downstream failure when it tries to pair this game's T-rows.
    teams_seen: dict[int, Team] = {}
    for row in t_rows:
        try:
            team = team_identity_from_row(row)
        except (KeyError, ValueError, TypeError):
            continue
        teams_seen[team.team_id] = team
    summary.teams_total, summary.teams_new = _upsert_teams(session, list(teams_seen.values()))
    session.flush()

    # Players. Skip malformed rows here too; the PGL loop below will count
    # them in pgls_errors. We don't double-count by adding a player-errors
    # field; identity extraction failure is essentially the same upstream
    # problem as PGL parsing failure.
    players_seen: dict[int, Player] = {}
    for row in p_rows:
        try:
            player = player_identity_from_row(row)
        except (KeyError, ValueError, TypeError):
            continue  # logged when the PGL loop hits the same row
        players_seen[player.player_id] = player
    summary.players_total, summary.players_new = _upsert_players(
        session, list(players_seen.values())
    )
    session.flush()

    # Games. Group T-rows by GAME_ID; each game has two T-rows.
    existing_games = _existing_game_ids(session, season=season, season_type=season_type)
    existing_results = _existing_result_game_ids(session, season=season, season_type=season_type)

    by_game: dict[str, list[dict[str, Any]]] = {}
    for row in t_rows:
        by_game.setdefault(str(row["GAME_ID"]), []).append(row)

    # First pass: insert Games. Collect (game_id, result) for the second pass.
    pending_results: list[GameResult] = []
    for game_id, rows in by_game.items():
        if len(rows) != 2:
            logger.warning(
                "GAME_ID %s has %d T-rows, expected 2; skipping",
                game_id,
                len(rows),
            )
            continue
        try:
            game, result = team_game_log_rows_to_orm(
                rows[0], rows[1], season=season, season_type=season_type
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping GAME_ID %s: %s", game_id, exc)
            summary.games_errors += 1
            continue

        if game_id in existing_games:
            summary.games_skipped += 1
        else:
            session.add(game)
            summary.games_inserted += 1

        if game_id in existing_results:
            summary.results_skipped += 1
        else:
            pending_results.append(result)

    # Flush Games so GameResult FKs resolve.
    session.flush()

    # GameResults. Reference the games we just flushed.
    for result in pending_results:
        session.add(result)
        summary.results_inserted += 1
    session.flush()

    # PlayerGameLogs. The key extraction lives inside the try because
    # malformed rows (missing PLAYER_ID, schema drift) can raise here
    # before we even reach the parser.
    existing_pgls = _existing_pgl_keys(session, season=season, season_type=season_type)
    for row in p_rows:
        try:
            key = (int(row["PLAYER_ID"]), str(row["GAME_ID"]))
            if key in existing_pgls:
                summary.pgls_skipped += 1
                continue
            pgl = player_game_log_row_to_orm(row, season=season, season_type=season_type)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping malformed P-row: %s", exc)
            summary.pgls_errors += 1
            continue
        session.add(pgl)
        summary.pgls_inserted += 1

    session.flush()

    summary.elapsed_seconds = time.monotonic() - start_time
    logger.info("\n%s", _format_summary(summary))
    return summary


def _format_summary(s: SeasonLoadSummary) -> str:
    games_err = f" errors {s.games_errors}" if s.games_errors else ""
    pgls_err = f" errors {s.pgls_errors}" if s.pgls_errors else ""
    return (
        f"{s.season} {s.season_type}\n"
        f"  T-rows: {s.t_rows:,}   P-rows: {s.p_rows:,}\n"
        f"  teams: {s.teams_total} (+{s.teams_new})  "
        f"players: {s.players_total} (+{s.players_new})\n"
        f"  games: +{s.games_inserted} (skipped {s.games_skipped}{games_err})  "
        f"results: +{s.results_inserted} (skipped {s.results_skipped})  "
        f"player_game_logs: +{s.pgls_inserted} (skipped {s.pgls_skipped}{pgls_err})\n"
        f"  done in {s.elapsed_seconds:.1f}s"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bulk_load",
        description="Bulk-load NBA box scores from LeagueGameLog into Postgres.",
    )
    parser.add_argument("--start", required=True, help="Starting season, e.g. '2022-23'")
    parser.add_argument("--end", required=True, help="Ending season (inclusive), e.g. '2024-25'")
    parser.add_argument(
        "--season-type",
        default="Regular Season",
        choices=["Regular Season", "Playoffs", "PlayIn"],
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    seasons = list(iter_seasons(args.start, args.end))
    logger.info("Loading %d season(s): %s", len(seasons), ", ".join(seasons))

    engine = get_engine()
    with Session(engine) as session, CachedHttpClient(session) as client:
        for season in seasons:
            try:
                load_season(client, session, season=season, season_type=args.season_type)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("Failed loading %s; rolled back this season", season)
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
