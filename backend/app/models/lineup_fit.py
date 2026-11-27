"""Fit and save lineup redistribution effects.

uv run python -m app.models.lineup_fit
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime

from sqlmodel import Session

from app.db.engine import get_engine
from app.models.lineup import (
    EMBIID_ID,
    LINEUP_VERSION,
    MAXEY_ID,
    fit_lineup_effects,
    lookup_delta,
    save_effects,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-out-games", type=int, default=3)
    parser.add_argument("--as-of", type=str, default=None, help="ISO datetime UTC")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    as_of = datetime.fromisoformat(args.as_of).astimezone(UTC) if args.as_of else datetime.now(UTC)
    with Session(get_engine()) as session:
        artifact = fit_lineup_effects(
            session,
            as_of=as_of,
            min_out_games=args.min_out_games,
        )
    path = save_effects(artifact)
    embiid_maxey = lookup_delta(
        artifact,
        injured_id=EMBIID_ID,
        beneficiary_id=MAXEY_ID,
        prop_type="points",
    )
    summary = {
        "model_version": LINEUP_VERSION,
        "n_effects": artifact["n_effects"],
        "artifact": str(path),
        "embiid_to_maxey_points_delta": embiid_maxey,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
