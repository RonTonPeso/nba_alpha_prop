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

Each contract is also scored as a probability. P(stat >= line) is the
upper tail of the stored normal. Brier, log loss, and the reliability
diagram use that probability. The yes mid is attached only when a
snapshot was visible at the same 16:00 UTC clock.

MAE is conditional on the player appearing in the box score. The
baseline does not predict who plays.

``--synthetic`` writes a 5-player, 7-day fixture so the metric section
can be regenerated without a database. Those rows are not NBA games.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session, select

from app.backtest.metrics import ProbTrial, probability_at_least, probability_section
from app.backtest.plots import reliability_svg
from app.backtest.quotes import latest_yes_mid
from app.db.engine import get_engine
from app.db.tables import Game, Market
from app.models.baseline import MODEL_VERSION, mean_absolute_error, over_hit_rate
from app.models.predict import (
    covered_player_ids,
    latest_logs_for_game,
    lines_for,
    predict_player_game,
    prediction_time_for,
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
    prob_trials: list[ProbTrial] = field(default_factory=list)
    covered_players: int = 0
    banner: str | None = None

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
                as_of = prediction_time_for(game.game_date)
                markets = session.exec(
                    select(Market).where(
                        Market.player_id == player_id,
                        Market.game_id == game.game_id,
                        Market.prop_type == forecast.prop_type,
                    )
                ).all()
                for market in markets:
                    outcome = 1 if actual >= market.line else 0
                    summary.prob_trials.append(
                        ProbTrial(
                            probability=probability_at_least(
                                forecast.mean,
                                forecast.std,
                                market.line,
                            ),
                            outcome=outcome,
                            market_probability=latest_yes_mid(session, market.ticker, as_of),
                        )
                    )
    return summary


def render_report(summary: ReplaySummary, *, chart_name: str) -> tuple[str, str | None]:
    mae = summary.mae
    hits = summary.hits
    if mae is None:
        mae_line = "MAE: not scored (no forecasts with a box score)"
    else:
        mae_line = f"MAE: {mae:.3f} on {len(summary.mae_pairs)} player-props"
    if hits is None and summary.forecasts == 0:
        hit_line = "Hit rate: not scored. No forecast was produced, so no line was compared."
    elif hits is None:
        hit_line = (
            "Hit rate: not scored. Forecasts were produced and no Kalshi line "
            "was joined for this window. NBA prop coverage on Kalshi starts "
            "November 2025, so an earlier month has nothing to grade as over."
        )
    else:
        hit_count, trials = hits
        rate = hit_count / trials
        hit_line = (
            f"Hit rate: {hit_count}/{trials} = {rate:.3f}. "
            "Over means predicted mean >= line and actual stat >= line."
        )
    probability_lines, bins = probability_section(summary.prob_trials, chart_name=chart_name)
    svg = None if bins is None else reliability_svg(bins)
    header = [
        f"# Baseline replay {summary.start.isoformat()} to {summary.end.isoformat()}",
        "",
    ]
    if summary.banner is not None:
        header.extend([summary.banner, ""])
    header.extend(
        [
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
            "Hit rate counts each distinct Kalshi line once.",
            "Brier and log loss count each Kalshi contract once.",
            "All three are conditional on the player appearing in the box score.",
            "A handful of games is a sample. The held-out month is a separate check.",
            "",
            *probability_lines,
            "",
        ]
    )
    return "\n".join(header), svg


def synthetic_week_summary() -> ReplaySummary:
    """Five players, seven days, one contract each. Typed numbers, not games.

    Every contract is probability 0.25 and outcome 0, so Brier is 0.0625.
    The CI smoke test locks that value. Nothing here is an NBA result.
    """
    summary = ReplaySummary(start=date(2026, 1, 1), end=date(2026, 1, 7))
    summary.games_seen = 7
    summary.covered_players = 5
    summary.forecasts = 35
    summary.mae_pairs = [(10.0, 8.0)] * 35
    summary.hit_trials = [(10.0, 8.0, 10.5)] * 35
    summary.prob_trials = [ProbTrial(0.25, 0, None) for _ in range(35)]
    summary.banner = (
        "SYNTHETIC. Five players, seven days, one contract each, typed in "
        "so the probability section can be checked without a database. "
        "These are not NBA games and not a track record."
    )
    return summary


def default_report_path(start: date, end: date) -> Path:
    directory = _REPO_ROOT / "docs" / "results"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"m4-calibration-{start.isoformat()}-{end.isoformat()}.md"


def synthetic_report_path() -> Path:
    directory = _REPO_ROOT / "docs" / "results"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "m4-calibration-synthetic.md"


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _write_report(summary: ReplaySummary, output: Path) -> None:
    if not output.is_absolute():
        output = _REPO_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    chart_name = output.with_suffix(".svg").name
    text, svg = render_report(summary, chart_name=chart_name)
    output.write_text(text)
    if svg is not None:
        output.with_suffix(".svg").write_text(svg)
        print(f"wrote {output.with_suffix('.svg')}")
    print(text)
    print(f"wrote {output}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backtest.run",
        description="Replay the M3 baseline and write a calibration report.",
    )
    parser.add_argument("--start", default=None, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD, inclusive")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Write the 5-player, 7-day fixture. Does not read the database.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Report path. Default: docs/results/m4-calibration-<start>-<end>.md",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.synthetic:
        summary = synthetic_week_summary()
        output = Path(args.output) if args.output else synthetic_report_path()
        _write_report(summary, output)
        return 0

    if args.start is None or args.end is None:
        parser.error("--start and --end are required unless --synthetic is set")
    start = _parse_date(args.start)
    end = _parse_date(args.end)
    engine = get_engine()
    with Session(engine) as session:
        summary = replay(session, start=start, end=end)
        session.commit()
    output = Path(args.output) if args.output else default_report_path(start, end)
    _write_report(summary, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
