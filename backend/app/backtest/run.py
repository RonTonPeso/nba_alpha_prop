"""Replay the M3 baseline across a date range and write a report.

Usage, from ``backend/``::

    uv run python -m app.backtest.run --start 2025-01-01 --end 2025-01-31

The feature clock is ``prediction_time`` (16:00 UTC on the game date),
passed into ``query_player_game_logs``. Bulk-loaded history is visible
only when its ``ingested_at`` is at or before that clock. A January 2025
replay against rows ingested in 2026 will abstain. That is the leak
guard working. The report says so instead of dropping the filter.

Hit rate needs a Kalshi line on that player, game, and prop. Kalshi's
NBA props start in November 2025, so a January 2025 window can still
produce MAE and will usually have no lines. The report does not invent
a 50% hit rate for that case.

MAE is conditional on the player appearing in the box score. The
baseline does not predict who plays.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.db.tables import Game
from app.models.baseline import MODEL_VERSION, mean_absolute_error, over_hit_rate
from app.models.predict import (
    covered_player_ids,
    latest_logs_for_game,
    lines_for,
    predict_player_game,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class ReplaySummary:
    start: date
    end: date
    games_seen: int = 0
    forecasts: int = 0
    abstained: int = 0
    skipped_team: int = 0
    mae_pairs: list[tuple[float, float]] = field(default_factory=list)
    hit_trials: list[tuple[float, float, float]] = field(default_factory=list)
    covered_players: int = 0

    @property
    def mae(self) -> float | None:
        return mean_absolute_error(self.mae_pairs)

    @property
    def hits(self) -> tuple[int, int] | None:
        return over_hit_rate(self.hit_trials)


def _actual(log_points: float, log_rebounds: float, log_assists: float, prop_type: str) -> float:
    if prop_type == "points":
        return log_points
    if prop_type == "rebounds":
        return log_rebounds
    if prop_type == "assists":
        return log_assists
    raise ValueError(f"unsupported prop_type {prop_type!r}")


def replay(
    session: Session,
    *,
    start: date,
    end: date,
) -> ReplaySummary:
    """Score every game in ``[start, end]`` for Kalshi-resolved players.

    Caller commits if the inserted prediction rows should persist.
    """
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    summary = ReplaySummary(start=start, end=end)
    covered = covered_player_ids(session)
    summary.covered_players = len(covered)
    games = session.exec(select(Game).where(Game.game_date >= start, Game.game_date <= end)).all()
    for game in sorted(games, key=lambda item: (item.game_date, item.game_id)):
        summary.games_seen += 1
        labels = latest_logs_for_game(session, game.game_id)
        for player_id, log in labels.items():
            if player_id not in covered:
                continue
            forecasts, part = predict_player_game(session, player_id=player_id, game=game)
            summary.abstained += part.abstained
            summary.skipped_team += part.skipped_team
            summary.forecasts += len(forecasts)
            for forecast in forecasts:
                actual = _actual(
                    float(log.points),
                    float(log.rebounds),
                    float(log.assists),
                    forecast.prop_type,
                )
                summary.mae_pairs.append((forecast.mean, actual))
                for line in lines_for(
                    session,
                    player_id=player_id,
                    game_id=game.game_id,
                    prop_type=forecast.prop_type,
                ):
                    summary.hit_trials.append((forecast.mean, actual, line))
    return summary


def render_report(summary: ReplaySummary) -> str:
    mae = summary.mae
    hits = summary.hits
    if mae is None:
        mae_line = "MAE: not scored (no forecasts with a box score)"
    else:
        mae_line = f"MAE: {mae:.3f} on {len(summary.mae_pairs)} player-props"
    if hits is None:
        hit_line = (
            "Hit rate: not scored. No Kalshi line was joined for this window. "
            "NBA prop coverage on Kalshi starts November 2025, so an earlier "
            "month cannot answer the over/under question."
        )
    else:
        hit_count, trials = hits
        rate = hit_count / trials
        hit_line = (
            f"Hit rate: {hit_count}/{trials} = {rate:.3f}. "
            "Over means predicted mean >= line and actual stat >= line."
        )
    return "\n".join(
        [
            f"# Baseline replay {summary.start.isoformat()} to {summary.end.isoformat()}",
            "",
            f"Model version: `{MODEL_VERSION}`.",
            "",
            "This is the rolling-mean baseline.",
            "It is not the XGBoost model and not the Bayesian posterior.",
            "",
            "Features use `query_player_game_logs` at 16:00 UTC on the game date.",
            "Both `event_time` and `ingested_at` have to fall before that clock.",
            "A bulk load whose `ingested_at` is the fetch day will not be visible",
            "to a replay set before that fetch.",
            "",
            f"Games in range: {summary.games_seen}",
            f"Kalshi-resolved players in the database: {summary.covered_players}",
            f"Forecasts scored: {summary.forecasts}",
            f"Abstained (fewer than 5 prior games): {summary.abstained}",
            f"Skipped (prior team not in this game): {summary.skipped_team}",
            mae_line,
            hit_line,
            "",
            "MAE counts each player-prop once.",
            "Hit rate counts each Kalshi line separately.",
            "Both are conditional on the player appearing in the box score.",
            "",
        ]
    )


def default_report_path(start: date, end: date) -> Path:
    directory = _REPO_ROOT / "docs" / "results"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"m3-baseline-{start.isoformat()}-{end.isoformat()}.md"


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backtest.run",
        description="Replay the M3 baseline and write a markdown report.",
    )
    parser.add_argument("--start", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument(
        "--output",
        default=None,
        help="Report path. Default: docs/results/m3-baseline-<start>-<end>.md",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    engine = get_engine()
    with Session(engine) as session:
        summary = replay(session, start=start, end=end)
        session.commit()
    text = render_report(summary)
    output = Path(args.output) if args.output else default_report_path(start, end)
    if not output.is_absolute():
        output = _REPO_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    print(text)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
