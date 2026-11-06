"""Auto-match unmapped Kalshi player names to NBA player_ids.

Reads the markets table for distinct kalshi_player_name values that
still have NULL player_id, joins against the players table, and appends
any exact-or-normalized matches to kalshi_player_aliases.csv. Prints the
unmatched names so the user can hand-resolve the tricky ones (nicknames,
non-standard spellings, etc.).

Normalization strips Unicode combining marks so "Nikola Jokić" matches
"Nikola Jokic" (stats.nba.com strips accents in many places).

Run:
    uv run python -m app.data.kalshi_auto_match_aliases
"""

import argparse
import csv
import logging
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.db.tables import Market, Player

logger = logging.getLogger(__name__)

_DEFAULT_CSV_PATH = Path(__file__).parent / "kalshi_player_aliases.csv"


def _normalize(name: str) -> str:
    """Strip accents, lowercase, collapse whitespace.

    "Nikola Jokić" -> "nikola jokic"
    "Dennis Schröder" -> "dennis schroder"
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ASCII", "ignore").decode("ASCII")
    return " ".join(ascii_only.lower().split())


@dataclass
class MatchSummary:
    unmapped_total: int = 0
    exact_matches: int = 0
    normalized_matches: int = 0
    ambiguous: int = 0  # multiple players match the normalized form
    unmatched: list[str] = field(default_factory=list)
    already_in_csv: int = 0
    newly_appended: int = 0


def auto_match(session: Session, csv_path: Path = _DEFAULT_CSV_PATH) -> MatchSummary:
    """Build the alias map, append matches to CSV, return summary."""
    summary = MatchSummary()

    unmapped_names = list(
        session.exec(
            select(Market.kalshi_player_name).where(Market.player_id.is_(None)).distinct()  # type: ignore[union-attr]
        ).all()
    )
    summary.unmapped_total = len(unmapped_names)
    if not unmapped_names:
        logger.info("No unmapped Kalshi player names; nothing to match.")
        return summary

    players = list(session.exec(select(Player)).all())
    exact_lookup: dict[str, int] = {p.current_name: p.player_id for p in players}
    norm_lookup: dict[str, list[int]] = {}
    for p in players:
        key = _normalize(p.current_name)
        norm_lookup.setdefault(key, []).append(p.player_id)

    existing_csv_names: set[str] = set()
    if csv_path.exists():
        with csv_path.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_csv_names.add(row["kalshi_player_name"].strip())

    resolved: list[tuple[str, int]] = []
    for kalshi_name in unmapped_names:
        if kalshi_name in existing_csv_names:
            summary.already_in_csv += 1
            continue

        if kalshi_name in exact_lookup:
            resolved.append((kalshi_name, exact_lookup[kalshi_name]))
            summary.exact_matches += 1
            continue

        norm = _normalize(kalshi_name)
        candidates = norm_lookup.get(norm, [])
        if len(candidates) == 1:
            resolved.append((kalshi_name, candidates[0]))
            summary.normalized_matches += 1
        elif len(candidates) > 1:
            summary.ambiguous += 1
            summary.unmatched.append(f"{kalshi_name}  (ambiguous: {candidates})")
        else:
            summary.unmatched.append(kalshi_name)

    if resolved:
        # Append to CSV. Preserve header if file is empty/header-only.
        needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with csv_path.open("a", newline="") as f:
            writer = csv.writer(f)
            if needs_header:
                writer.writerow(["kalshi_player_name", "player_id"])
            for kalshi_name, pid in resolved:
                writer.writerow([kalshi_name, pid])
        summary.newly_appended = len(resolved)

    return summary


def _format_summary(s: MatchSummary, csv_path: Path) -> str:
    lines = [
        f"Auto-match against {csv_path.name}:",
        f"  unmapped Kalshi names: {s.unmapped_total}",
        f"  already in CSV: {s.already_in_csv}",
        f"  exact matches: +{s.exact_matches}",
        f"  normalized (accent-stripped) matches: +{s.normalized_matches}",
        f"  ambiguous (multiple players matched): {s.ambiguous}",
        f"  appended to CSV: {s.newly_appended}",
        f"  unmatched: {len(s.unmatched)}",
    ]
    if s.unmatched:
        lines.append("")
        lines.append("Names you'll need to hand-add to the CSV:")
        for n in s.unmatched:
            lines.append(f"  {n}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kalshi_auto_match_aliases",
        description="Auto-match unmapped Kalshi player names to NBA player_ids.",
    )
    parser.add_argument("--csv", type=Path, default=_DEFAULT_CSV_PATH)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    engine = get_engine()
    with Session(engine) as session:
        summary = auto_match(session, csv_path=args.csv)
        session.commit()  # no DB writes, but harmless

    logger.info(_format_summary(summary, args.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
