"""Seed kalshi_player_aliases from the versioned CSV.

CSV at ``app/data/kalshi_player_aliases.csv`` is the source of truth.
Edits go through PRs. This CLI is idempotent: re-running upserts any
new rows and updates ``player_id`` on rows whose alias name already
exists but maps to a different player.

Run:
    uv run python -m app.data.kalshi_seed_aliases
"""

import argparse
import csv
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from app.db.engine import get_engine
from app.db.tables import KalshiPlayerAlias

logger = logging.getLogger(__name__)

_DEFAULT_CSV_PATH = Path(__file__).parent / "kalshi_player_aliases.csv"


@dataclass
class SeedSummary:
    inserted: int = 0
    updated: int = 0  # name existed, player_id changed
    unchanged: int = 0
    csv_rows: int = 0


def seed_aliases(session: Session, csv_path: Path = _DEFAULT_CSV_PATH) -> SeedSummary:
    """Upsert rows from CSV into kalshi_player_aliases. Caller commits."""
    summary = SeedSummary()
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            summary.csv_rows += 1
            name = row["kalshi_player_name"].strip()
            player_id = int(row["player_id"])
            existing = session.get(KalshiPlayerAlias, name)
            if existing is None:
                session.add(KalshiPlayerAlias(kalshi_player_name=name, player_id=player_id))
                summary.inserted += 1
            elif existing.player_id != player_id:
                existing.player_id = player_id
                summary.updated += 1
            else:
                summary.unchanged += 1
    session.flush()
    return summary


def _format_summary(s: SeedSummary, csv_path: Path) -> str:
    return (
        f"Seeded kalshi_player_aliases from {csv_path}: "
        f"{s.csv_rows} CSV rows -> +{s.inserted} new, "
        f"{s.updated} updated, {s.unchanged} unchanged"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kalshi_seed_aliases",
        description="Seed kalshi_player_aliases from a CSV.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=_DEFAULT_CSV_PATH,
        help=f"Path to the alias CSV. Default: {_DEFAULT_CSV_PATH}",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    engine = get_engine()
    with Session(engine) as session:
        try:
            summary = seed_aliases(session, csv_path=args.csv)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Seed failed; rolled back")
            return 1
    logger.info(_format_summary(summary, args.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
