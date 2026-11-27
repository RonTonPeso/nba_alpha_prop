"""Timed scrape → classify → store CLI for M7 acceptance.

uv run python -m app.data.injury.run --timed
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from app.data.injury.pipeline import run_injury_pipeline
from app.db.engine import get_engine

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timed", action="store_true", help="record wall-clock seconds")
    parser.add_argument("--rss-only", action="store_true")
    parser.add_argument("--official-only", action="store_true")
    parser.add_argument("--rss-limit", type=int, default=15)
    parser.add_argument("--max-classify", type=int, default=40)
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="optional JSON path for the run summary",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    include_official = not args.rss_only
    include_rss = not args.official_only

    started = time.perf_counter()
    with Session(get_engine()) as session:
        summary = run_injury_pipeline(
            session,
            include_official=include_official,
            include_rss=include_rss,
            rss_limit=args.rss_limit,
            max_classify=args.max_classify,
        )
    elapsed = time.perf_counter() - started
    if args.timed:
        summary.seconds = elapsed

    payload = {
        "scraped": summary.scraped,
        "classified": summary.classified,
        "inserted": summary.inserted,
        "skipped_duplicate": summary.skipped_duplicate,
        "unresolved_player": summary.unresolved_player,
        "seconds": summary.seconds,
        "errors": summary.errors,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "under_300s": (summary.seconds is not None and summary.seconds < 300),
    }
    print(json.dumps(payload, indent=2))

    report_path = args.report_path
    if report_path is None and args.timed:
        report_path = _REPO_ROOT / "docs" / "results" / "m7-injury-timed.json"
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2) + "\n")
        logger.info("wrote %s", report_path)

    if args.timed and (summary.seconds is None or summary.seconds >= 300):
        return 2
    if summary.inserted < 1 and summary.skipped_duplicate < 1:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
