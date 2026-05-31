"""Spot-check helper: print box scores for N random games.

Read-only. Run after the bulk load to manually compare against
basketball-reference.com before declaring the data trustworthy.

    uv run python -m app.data.spot_check --n 3 [--seed 42]
"""

import argparse
import random
import sys
from collections.abc import Iterable

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.db.tables import Game, GameResult, Player, PlayerGameLog, Team


def _format_minutes(m: float | None) -> str:
    if m is None:
        return "DNP"
    whole = int(m)
    secs = int(round((m - whole) * 60))
    return f"{whole}:{secs:02d}"


def _format_team_block(
    team_label: str,
    pgls: Iterable[PlayerGameLog],
    name_by_player_id: dict[int, str],
) -> str:
    lines = [team_label]
    # Sort by points descending (most impactful at top, easy to scan).
    sorted_pgls = sorted(pgls, key=lambda p: p.points, reverse=True)
    for p in sorted_pgls:
        name = name_by_player_id.get(p.player_id, f"player {p.player_id}")
        lines.append(
            f"  {name:<22} {p.points:>3} pts  {p.rebounds:>2} reb  "
            f"{p.assists:>2} ast  {_format_minutes(p.minutes):>5}"
        )
    return "\n".join(lines)


def format_game(session: Session, game_id: str) -> str:
    """Build a basketball-reference-comparable box score for one game."""
    game = session.get(Game, game_id)
    if game is None:
        return f"GAME_ID {game_id} not found"

    result = session.exec(select(GameResult).where(GameResult.game_id == game_id)).first()

    home_team = session.get(Team, game.home_team_id)
    away_team = session.get(Team, game.away_team_id)
    home_name = f"{home_team.city} {home_team.name}" if home_team else "Home"
    away_name = f"{away_team.city} {away_team.name}" if away_team else "Away"

    pgls = list(session.exec(select(PlayerGameLog).where(PlayerGameLog.game_id == game_id)).all())

    name_by_player_id: dict[int, str] = {}
    for pgl in pgls:
        player = session.get(Player, pgl.player_id)
        if player is not None:
            name_by_player_id[pgl.player_id] = player.current_name

    home_pgls = [p for p in pgls if p.team_id == game.home_team_id]
    away_pgls = [p for p in pgls if p.team_id == game.away_team_id]

    header = f"{game.game_date}  {away_team.abbreviation if away_team else '???'} @ "
    header += f"{home_team.abbreviation if home_team else '???'}  "
    if result is not None:
        header += f"{result.away_score}-{result.home_score}"

    blocks = [
        header,
        _format_team_block(f"{away_name} (away)", away_pgls, name_by_player_id),
        _format_team_block(f"{home_name} (home)", home_pgls, name_by_player_id),
    ]
    return "\n".join(blocks)


def pick_random_game_ids(session: Session, n: int, *, seed: int | None = None) -> list[str]:
    """Pick up to N random game_ids from the DB. Stable when ``seed`` is given."""
    all_ids = list(session.exec(select(Game.game_id)).all())
    if not all_ids:
        return []
    rng = random.Random(seed)
    return rng.sample(all_ids, min(n, len(all_ids)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spot_check",
        description="Print box scores for N random games for basketball-reference comparison.",
    )
    parser.add_argument("--n", type=int, default=3, help="Number of games (default 3)")
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed")
    args = parser.parse_args(argv)

    engine = get_engine()
    with Session(engine) as session:
        game_ids = pick_random_game_ids(session, args.n, seed=args.seed)
        if not game_ids:
            print("No games found in the DB. Run bulk_load first.")
            return 1
        for game_id in game_ids:
            print(format_game(session, game_id))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
