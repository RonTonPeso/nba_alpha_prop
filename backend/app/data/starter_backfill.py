"""Backfill ``player_game_logs.started`` from traditional box scores.

Uses ``boxscoretraditionalv2`` ``START_POSITION``. Non-empty means
started. Idempotent: rows that already have ``started`` set are skipped
unless ``--force``.

    uv run python -m app.data.starter_backfill --start 2024-10-01 --end 2025-04-15
"""

from __future__ import annotations

import argparse
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sqlmodel import Session, col, select

from app.data.cache import CachedHttpClient
from app.data.nba import fetch_box_score_traditional, started_from_start_position
from app.db.engine import get_engine
from app.db.tables import Game, PlayerGameLog, Team

logger = logging.getLogger(__name__)

# Usual-starter window used by the lineup fit. Documented in provenance
# after a one-pass count; these are the locked defaults for M7.
USUAL_STARTER_WINDOW = 10
USUAL_STARTER_MIN_STARTS = 6


@dataclass
class BackfillSummary:
    games_seen: int = 0
    games_fetched: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    games_failed: int = 0


def backfill_game(
    session: Session,
    client: CachedHttpClient,
    game_id: str,
    *,
    force: bool = False,
) -> tuple[int, int]:
    """Update started flags for one game. Returns (updated, skipped)."""
    logs = list(session.exec(select(PlayerGameLog).where(PlayerGameLog.game_id == game_id)).all())
    if not logs:
        return 0, 0
    if not force and all(row.started is not None for row in logs):
        return 0, len(logs)

    rows = fetch_box_score_traditional(client, game_id=game_id)
    by_player: dict[int, bool] = {}
    for row in rows:
        try:
            player_id = int(row["PLAYER_ID"])
        except (KeyError, TypeError, ValueError):
            continue
        started = started_from_start_position(row.get("START_POSITION"))
        by_player[player_id] = started
        # Keep the raw box fields without wiping LeagueGameLog raw_data.
        matching = [log for log in logs if log.player_id == player_id]
        for log in matching:
            raw = dict(log.raw_data or {})
            raw["START_POSITION"] = row.get("START_POSITION")
            raw["boxscoretraditionalv2"] = True
            log.raw_data = raw

    updated = 0
    skipped = 0
    for log in logs:
        if log.player_id not in by_player:
            skipped += 1
            continue
        if not force and log.started is not None:
            skipped += 1
            continue
        log.started = by_player[log.player_id]
        updated += 1
    return updated, skipped


def backfill_date_range(
    session: Session,
    *,
    start: date,
    end: date,
    force: bool = False,
    sleep_seconds: float = 0.6,
    limit_games: int | None = None,
    team_abbr: str | None = None,
) -> BackfillSummary:
    summary = BackfillSummary()
    statement = (
        select(Game)
        .where(Game.game_date >= start)
        .where(Game.game_date <= end)
        .order_by(col(Game.game_date), col(Game.game_id))
    )
    if team_abbr is not None:
        team = session.exec(select(Team).where(Team.abbreviation == team_abbr.upper())).first()
        if team is None:
            raise ValueError(f"unknown team abbreviation {team_abbr!r}")
        statement = statement.where(
            (Game.home_team_id == team.team_id) | (Game.away_team_id == team.team_id)
        )
    games = list(session.exec(statement).all())
    if limit_games is not None:
        games = games[:limit_games]

    with CachedHttpClient(session) as client:
        for game in games:
            summary.games_seen += 1
            try:
                updated, skipped = backfill_game(session, client, game.game_id, force=force)
            except Exception:
                logger.exception("starter backfill failed for game %s", game.game_id)
                summary.games_failed += 1
                session.rollback()
                continue
            summary.games_fetched += 1
            summary.rows_updated += updated
            summary.rows_skipped += skipped
            session.commit()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            if summary.games_fetched % 25 == 0:
                logger.info(
                    "starter backfill progress games=%d updated=%d failed=%d",
                    summary.games_fetched,
                    summary.rows_updated,
                    summary.games_failed,
                )
    return summary


def usual_starters_for_team(
    session: Session,
    *,
    team_id: int,
    as_of: datetime,
    window: int = USUAL_STARTER_WINDOW,
    min_starts: int = USUAL_STARTER_MIN_STARTS,
) -> set[int]:
    """Players who started at least ``min_starts`` of the prior ``window`` team games."""
    # Recent team games that already have starter flags, newest first.
    flagged = list(
        session.exec(
            select(PlayerGameLog.game_id, PlayerGameLog.event_time)
            .where(PlayerGameLog.team_id == team_id)
            .where(PlayerGameLog.event_time < as_of)
            .where(PlayerGameLog.available_at <= as_of)
            .where(PlayerGameLog.started.is_not(None))  # type: ignore[union-attr]
            .order_by(col(PlayerGameLog.event_time).desc())
        ).all()
    )
    seen_games: list[str] = []
    seen_set: set[str] = set()
    for game_id, _event_time in flagged:
        gid = str(game_id)
        if gid in seen_set:
            continue
        seen_set.add(gid)
        seen_games.append(gid)
        if len(seen_games) >= window:
            break
    if not seen_games:
        return set()

    start_counts: dict[int, int] = defaultdict(int)
    for game_id in seen_games:
        starters = session.exec(
            select(PlayerGameLog.player_id).where(
                PlayerGameLog.game_id == game_id,
                PlayerGameLog.team_id == team_id,
                PlayerGameLog.started.is_(True),  # type: ignore[union-attr]
            )
        ).all()
        for player_id in starters:
            start_counts[int(player_id)] += 1
    return {player_id for player_id, count in start_counts.items() if count >= min_starts}


def starters_out_for_game(
    session: Session,
    *,
    team_id: int,
    game_id: int | str,
    as_of: datetime,
    window: int = USUAL_STARTER_WINDOW,
    min_starts: int = USUAL_STARTER_MIN_STARTS,
) -> set[int]:
    """Usual starters who did not start (or did not appear) in ``game_id``."""
    usual = usual_starters_for_team(
        session,
        team_id=team_id,
        as_of=as_of,
        window=window,
        min_starts=min_starts,
    )
    if not usual:
        return set()
    appeared = {
        int(pid)
        for pid in session.exec(
            select(PlayerGameLog.player_id).where(
                PlayerGameLog.game_id == str(game_id),
                PlayerGameLog.team_id == team_id,
            )
        ).all()
    }
    started = {
        int(pid)
        for pid in session.exec(
            select(PlayerGameLog.player_id).where(
                PlayerGameLog.game_id == str(game_id),
                PlayerGameLog.team_id == team_id,
                PlayerGameLog.started.is_(True),  # type: ignore[union-attr]
            )
        ).all()
    }
    out: set[int] = set()
    for player_id in usual:
        if player_id not in appeared:
            out.add(player_id)
        elif player_id not in started:
            out.add(player_id)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.6)
    parser.add_argument("--limit-games", type=int, default=None)
    parser.add_argument("--team", type=str, default=None, help="Team abbreviation, e.g. PHI")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    with Session(get_engine()) as session:
        summary = backfill_date_range(
            session,
            start=start,
            end=end,
            force=args.force,
            sleep_seconds=args.sleep,
            limit_games=args.limit_games,
            team_abbr=args.team,
        )
    print(
        f"games_seen={summary.games_seen} fetched={summary.games_fetched} "
        f"updated={summary.rows_updated} skipped={summary.rows_skipped} "
        f"failed={summary.games_failed}"
    )
    return 0 if summary.games_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
