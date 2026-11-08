"""Fit the M5 boosters and write the holdout comparison.

Usage, from ``backend/``::

    uv run python -m app.models.fit

One booster per prop, fixed hyperparameters, last 20 percent of game
dates held out. Feature rows use ``available_at``. The baseline compared
here is recomputed with ``forecast_prop`` on the same visible history.
Previously stored ``baseline-m3-v1`` rows are not the comparison.

The command stores ``xgb-m5-v1`` for the holdout and writes any missing
baseline row for that same holdout. It does not start the scheduler.
"""

from __future__ import annotations

import argparse
import logging
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlmodel import Session

from app.backtest.metrics import brier_score, probability_at_least
from app.db.tables import Prediction
from app.models.baseline import (
    PROP_TYPES,
    Forecast,
    HistoryGame,
    forecast_prop,
    mean_absolute_error,
)
from app.models.boost import (
    MODEL_VERSION,
    fit_regressor,
    hyperparameters,
    predict,
    probability_band,
    residual_std,
    shap_top,
    shipped_mean,
)
from app.models.compare import HOLDOUT_FRACTION, holdout_start, in_headline, verdict
from app.models.features import (
    FEATURE_NAMES,
    REST_CAP,
    PlayerLog,
    TeamPointsAllowed,
    build_feature_row,
    usage_units,
    visible_logs,
)
from app.models.predict import HISTORY_LIMIT, prediction_time_for

logger = logging.getLogger(__name__)

_RESULTS = Path(__file__).resolve().parents[3] / "docs" / "results" / "m5-xgb.md"


@dataclass(frozen=True)
class Example:
    player_id: int
    game_id: str
    game_date: date
    rest_days: int
    is_home: bool
    n_games: int
    features: tuple[float, ...]
    actual: tuple[float, float, float]
    baseline: tuple[Forecast, Forecast, Forecast]


@dataclass(frozen=True)
class _LoadedLog:
    player_id: int
    game_id: str
    game_date: date
    team_id: int
    home_team_id: int
    away_team_id: int
    is_home: bool
    event_time: datetime
    available_at: datetime
    points: float
    rebounds: float
    assists: float
    minutes: float | None
    fga: float
    fta: float
    tov: float

    def as_player_log(self) -> PlayerLog:
        return PlayerLog(
            game_id=self.game_id,
            game_date=self.game_date,
            team_id=self.team_id,
            is_home=self.is_home,
            event_time=self.event_time,
            available_at=self.available_at,
            points=self.points,
            rebounds=self.rebounds,
            assists=self.assists,
            minutes=self.minutes,
            fga=self.fga,
            fta=self.fta,
            tov=self.tov,
        )


def _examples_for_player(
    logs: Sequence[_LoadedLog],
    *,
    team_usage: Mapping[tuple[str, int], float],
    team_games: Mapping[int, Sequence[TeamPointsAllowed]],
) -> list[Example]:
    ordered = sorted(logs, key=lambda log: (log.event_time, log.game_id))
    player_logs = [log.as_player_log() for log in ordered]
    built: list[Example] = []
    for index, log in enumerate(ordered):
        as_of = prediction_time_for(log.game_date)
        row = build_feature_row(
            player_logs[:index],
            game_date=log.game_date,
            home_team_id=log.home_team_id,
            away_team_id=log.away_team_id,
            as_of=as_of,
            team_usage=team_usage,
            team_games=team_games,
        )
        if row is None:
            continue
        clocked = visible_logs(player_logs[:index], as_of)
        history = [
            HistoryGame(
                game_date=prior.game_date,
                is_home=prior.is_home,
                team_id=prior.team_id,
                points=prior.points,
                rebounds=prior.rebounds,
                assists=prior.assists,
            )
            for prior in clocked[:HISTORY_LIMIT]
        ]
        forecasts: list[Forecast] = []
        for prop_type in PROP_TYPES:
            forecast = forecast_prop(
                history,
                prop_type=prop_type,
                is_home=row.is_home,
                rest_days=row.rest_days,
            )
            if forecast is None:
                break
            forecasts.append(forecast)
        if len(forecasts) != len(PROP_TYPES):
            continue
        built.append(
            Example(
                player_id=log.player_id,
                game_id=log.game_id,
                game_date=log.game_date,
                rest_days=row.rest_days,
                is_home=row.is_home,
                n_games=row.n_games,
                features=row.values,
                actual=(log.points, log.rebounds, log.assists),
                baseline=(forecasts[0], forecasts[1], forecasts[2]),
            )
        )
    return built


def build_examples(
    logs: Sequence[_LoadedLog],
    *,
    team_usage: Mapping[tuple[str, int], float],
    team_games: Mapping[int, Sequence[TeamPointsAllowed]],
) -> list[Example]:
    by_player: dict[int, list[_LoadedLog]] = defaultdict(list)
    for log in logs:
        by_player[log.player_id].append(log)
    examples: list[Example] = []
    for player_logs in by_player.values():
        examples.extend(
            _examples_for_player(player_logs, team_usage=team_usage, team_games=team_games)
        )
    examples.sort(key=lambda example: (example.game_date, example.game_id, example.player_id))
    return examples


def _json_number(value: float) -> float | None:
    if math.isnan(value):
        return None
    return value


def _mae(pairs: list[tuple[float, float]]) -> float | None:
    return mean_absolute_error(pairs)


def render_report(
    *,
    holdout_on: date,
    train_dates: int,
    holdout_dates: int,
    train_rows: int,
    holdout_rows: int,
    headline_games: int,
    headline_rows: int,
    xgb_mae: float | None,
    baseline_mae: float | None,
    prop_mae: Sequence[tuple[str, float | None, float | None, int]],
    xgb_brier: float | None,
    baseline_brier: float | None,
    brier_contracts: int,
    long_gap_rows: int,
    long_gap_games: int,
    long_xgb_mae: float | None,
    long_baseline_mae: float | None,
    label: str,
    kalshi_games: int,
    kalshi_rows: int,
    kalshi_xgb_mae: float | None,
    kalshi_baseline_mae: float | None,
) -> str:
    def mae_text(value: float | None, rows: int) -> str:
        if value is None:
            return f"not scored (n={rows})"
        return f"{value:.3f} on {rows} player-props"

    def brier_text(value: float | None) -> str:
        if value is None:
            return "not scored"
        return f"{value:.6f} on {brier_contracts} contracts"

    lines = [
        "# M5 XGBoost comparison",
        "",
        f"Model version: `{MODEL_VERSION}`.",
        "Baseline version: `baseline-m3-v1`, recomputed on the same visible history.",
        "Stored baseline rows from an earlier clock are not these numbers.",
        "",
        "This is one booster per prop. It is not a posterior.",
        "The stored spread is the training residual of the clipped mean.",
        "",
        "Features use the 16:00 UTC clock.",
        "`event_time` has to be before that clock.",
        "`available_at` has to be at or before that clock.",
        "For a bulk-loaded box score, `available_at` is 12:00 UTC on the",
        "day after the game. `ingested_at` is the fetch time and is not",
        "the feature clock. Quotes are not scored in this comparison.",
        "",
        f"Holdout starts: {holdout_on.isoformat()} "
        f"(last {HOLDOUT_FRACTION:.0%} of game dates).",
        f"Training dates: {train_dates}. Holdout dates: {holdout_dates}.",
        f"Training player-games: {train_rows}. Holdout player-games: {holdout_rows}.",
        "",
        f"Headline keeps raw rest of {REST_CAP} days or less.",
        "A longer gap is low_confidence and is listed after the headline.",
        f"Headline games: {headline_games}.",
        f"XGBoost MAE: {mae_text(xgb_mae, headline_rows)}.",
        f"Baseline MAE: {mae_text(baseline_mae, headline_rows)}.",
        *[
            f"{prop_type} MAE: XGBoost {mae_text(xgb_value, rows)}, "
            f"baseline {mae_text(base_value, rows)}."
            for prop_type, xgb_value, base_value, rows in prop_mae
        ],
        f"Verdict: {label}.",
        "",
        "Brier uses P(stat >= line) from each model's normal band,",
        "on headline player-props that have a Kalshi line.",
        f"XGBoost Brier: {brier_text(xgb_brier)}.",
        f"Baseline Brier: {brier_text(baseline_brier)}.",
        "",
        "Players a Kalshi market has been resolved to, same headline rest cap:",
        f"Games: {kalshi_games}.",
        f"XGBoost MAE: {mae_text(kalshi_xgb_mae, kalshi_rows)}.",
        f"Baseline MAE: {mae_text(kalshi_baseline_mae, kalshi_rows)}.",
        "",
        "Rest over the cap, not the acceptance sample:",
        f"Games: {long_gap_games}.",
        f"XGBoost MAE: {mae_text(long_xgb_mae, long_gap_rows)}.",
        f"Baseline MAE: {mae_text(long_baseline_mae, long_gap_rows)}.",
        "",
        "Features, in column order: " + ", ".join(f"`{name}`" for name in FEATURE_NAMES) + ".",
        "`usage_share` divides the player's FGA + 0.44*FTA + TOV by that",
        "sum for every teammate on the same team in those games, including",
        "the player. `opp_pts_allowed_15` is the opponent's points allowed.",
        "Neither name is a defensive rating or a play-by-play usage rate.",
        "",
        "Fixed hyperparameters: "
        + ", ".join(f"`{key}={value}`" for key, value in hyperparameters().items())
        + ".",
        "No search was run. The holdout was not an eval set.",
        "",
    ]
    if label == "refused":
        lines.append("The comparison was refused. The milestone stays open.")
    elif label == "mixed":
        lines.append(
            "MAE improved and the residual Brier got worse. " "That is a mixed result, not a pass."
        )
    elif label == "not_better":
        lines.append("The baseline MAE was lower or equal. The milestone stays open.")
    elif label == "mae_only":
        lines.append(
            "MAE improved and no headline contract was scored. "
            "The Brier line of the milestone is still open."
        )
    else:
        lines.append("MAE improved and the residual Brier was not worse on the headline contracts.")
    lines.append("")
    return "\n".join(lines)


def _subset_pairs(
    rows: Sequence[Example],
    prop_index: int,
    predictions: Sequence[float],
    keep: Sequence[bool],
) -> list[tuple[float, float]]:
    return [
        (shipped_mean(predictions[index]), rows[index].actual[prop_index])
        for index in range(len(rows))
        if keep[index]
    ]


def _rows(session: Session, sql: str, params: dict[str, Any] | None = None) -> Sequence[Row[Any]]:
    return session.connection().execute(text(sql), params or {}).all()


def _load(session: Session) -> tuple[list[_LoadedLog], dict[int, list[TeamPointsAllowed]]]:
    game_rows = _rows(session, "SELECT game_id, game_date, home_team_id, away_team_id FROM games")
    games = {
        str(row.game_id): (row.game_date, int(row.home_team_id), int(row.away_team_id))
        for row in game_rows
    }
    log_rows = _rows(
        session,
        """
        SELECT DISTINCT ON (player_id, game_id)
            player_id, game_id, team_id, points, rebounds, assists, minutes,
            field_goals_attempted, free_throws_attempted, turnovers,
            event_time, available_at
        FROM player_game_logs
        ORDER BY player_id, game_id, ingested_at DESC
        """,
    )
    logs: list[_LoadedLog] = []
    for row in log_rows:
        game = games.get(str(row.game_id))
        if game is None:
            continue
        game_date, home_team_id, away_team_id = game
        team_id = int(row.team_id)
        logs.append(
            _LoadedLog(
                player_id=int(row.player_id),
                game_id=str(row.game_id),
                game_date=game_date,
                team_id=team_id,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                is_home=team_id == home_team_id,
                event_time=row.event_time,
                available_at=row.available_at,
                points=float(row.points),
                rebounds=float(row.rebounds),
                assists=float(row.assists),
                minutes=None if row.minutes is None else float(row.minutes),
                fga=float(row.field_goals_attempted),
                fta=float(row.free_throws_attempted),
                tov=float(row.turnovers),
            )
        )
    result_rows = _rows(
        session,
        """
        SELECT DISTINCT ON (game_id)
            game_id, home_score, away_score, event_time, available_at
        FROM game_results
        ORDER BY game_id, ingested_at DESC
        """,
    )
    team_games: dict[int, list[TeamPointsAllowed]] = defaultdict(list)
    for row in result_rows:
        game = games.get(str(row.game_id))
        if game is None:
            continue
        _game_date, home_team_id, away_team_id = game
        allowed = TeamPointsAllowed(
            event_time=row.event_time,
            available_at=row.available_at,
            points_allowed=float(row.away_score),
        )
        team_games[home_team_id].append(allowed)
        team_games[away_team_id].append(
            TeamPointsAllowed(
                event_time=row.event_time,
                available_at=row.available_at,
                points_allowed=float(row.home_score),
            )
        )
    for entries in team_games.values():
        entries.sort(key=lambda item: (item.event_time, item.available_at))
    return logs, team_games


def _team_usage(logs: Sequence[_LoadedLog]) -> dict[tuple[str, int], float]:
    totals: dict[tuple[str, int], float] = defaultdict(float)
    for log in logs:
        totals[(log.game_id, log.team_id)] += usage_units(log.fga, log.fta, log.tov)
    return totals


def _lines(
    session: Session,
) -> dict[tuple[int, str, str], list[float]]:
    rows = _rows(
        session,
        """
        SELECT player_id, game_id, prop_type, line
        FROM markets
        WHERE player_id IS NOT NULL
          AND game_id IS NOT NULL
        """,
    )
    found: dict[tuple[int, str, str], set[float]] = defaultdict(set)
    for row in rows:
        if row.prop_type not in PROP_TYPES:
            continue
        found[(int(row.player_id), str(row.game_id), str(row.prop_type))].add(float(row.line))
    return {key: sorted(values) for key, values in found.items()}


def _kalshi_players(session: Session) -> set[int]:
    rows = _rows(session, "SELECT DISTINCT player_id FROM markets WHERE player_id IS NOT NULL")
    return {int(row.player_id) for row in rows}


def _existing(session: Session, model_version: str) -> set[tuple[int, str, str]]:
    rows = _rows(
        session,
        """
        SELECT player_id, game_id, prop_type
        FROM predictions
        WHERE model_version = :model_version
        """,
        {"model_version": model_version},
    )
    return {(int(row.player_id), str(row.game_id), str(row.prop_type)) for row in rows}


def _store_baseline(session: Session, example: Example, forecast: Forecast) -> None:
    session.add(
        Prediction(
            player_id=example.player_id,
            game_id=example.game_id,
            prop_type=forecast.prop_type,
            model_version=forecast.model_version,
            prediction_time=prediction_time_for(example.game_date),
            mean=forecast.mean,
            std=forecast.std,
            quantile_10=forecast.quantile_10,
            quantile_50=forecast.quantile_50,
            quantile_90=forecast.quantile_90,
            n_games=forecast.n_games,
            low_confidence=forecast.low_confidence,
            payload=dict(forecast.payload()),
        )
    )


def _store_xgb(
    session: Session,
    *,
    example: Example,
    prop_index: int,
    mean: float,
    std: float,
    contributions: list[tuple[str, float]],
    train_std_note: float,
) -> None:
    prop_type = PROP_TYPES[prop_index]
    center = shipped_mean(mean)
    low, mid, high = probability_band(center, std)
    session.add(
        Prediction(
            player_id=example.player_id,
            game_id=example.game_id,
            prop_type=prop_type,
            model_version=MODEL_VERSION,
            prediction_time=prediction_time_for(example.game_date),
            mean=center,
            std=std,
            quantile_10=low,
            quantile_50=mid,
            quantile_90=high,
            n_games=example.n_games,
            low_confidence=not in_headline(example.rest_days),
            payload={
                "distribution": "residual-normal",
                "features": {
                    name: _json_number(value)
                    for name, value in zip(FEATURE_NAMES, example.features, strict=True)
                },
                "shap_top5": [
                    {"feature": name, "shap": shap_value} for name, shap_value in contributions
                ],
                "residual_std": train_std_note,
                "rest_days": example.rest_days,
                "rest_capped": min(example.rest_days, REST_CAP),
                "is_home": example.is_home,
                "hyperparameters": hyperparameters(),
            },
        )
    )


def run(session: Session, *, fraction: float = HOLDOUT_FRACTION) -> str:
    """Fit, score, store the holdout, and return the report text."""
    logs, team_games = _load(session)
    logger.info("loaded %d player-games", len(logs))
    examples = build_examples(logs, team_usage=_team_usage(logs), team_games=team_games)
    if not examples:
        raise RuntimeError("no feature rows were built")
    start = holdout_start((example.game_date for example in examples), fraction)
    train = [example for example in examples if example.game_date < start]
    holdout = [example for example in examples if example.game_date >= start]
    if not train or not holdout:
        raise RuntimeError("the date cut left one side empty")
    logger.info("train %d holdout %d from %s", len(train), len(holdout), start.isoformat())

    train_x = np.asarray([example.features for example in train], dtype=np.float64)
    hold_x = np.asarray([example.features for example in holdout], dtype=np.float64)
    headline = [in_headline(example.rest_days) for example in holdout]
    headline_rows = [example for example, keep in zip(holdout, headline, strict=True) if keep]
    long_rows = [example for example, keep in zip(holdout, headline, strict=True) if not keep]

    shipped: list[list[float]] = []
    spreads: list[float] = []
    contributions: list[list[list[tuple[str, float]]]] = []
    for prop_index in range(len(PROP_TYPES)):
        target = [example.actual[prop_index] for example in train]
        model = fit_regressor(train_x, np.asarray(target, dtype=np.float64))
        train_pred = predict(model, train_x)
        hold_pred = predict(model, hold_x)
        spread = residual_std(target, train_pred)
        shipped.append(hold_pred)
        spreads.append(spread)
        contributions.append(shap_top(model, hold_x, FEATURE_NAMES))
        logger.info("%s residual std %.3f", PROP_TYPES[prop_index], spread)

    def collect(rows_keep: list[bool]) -> tuple[float | None, float | None, int]:
        xgb_pairs: list[tuple[float, float]] = []
        base_pairs: list[tuple[float, float]] = []
        for prop_index in range(len(PROP_TYPES)):
            xgb_pairs.extend(_subset_pairs(holdout, prop_index, shipped[prop_index], rows_keep))
            base_pairs.extend(
                (
                    holdout[index].baseline[prop_index].mean,
                    holdout[index].actual[prop_index],
                )
                for index in range(len(holdout))
                if rows_keep[index]
            )
        return _mae(xgb_pairs), _mae(base_pairs), len(xgb_pairs)

    xgb_mae, baseline_mae, headline_n = collect(headline)
    prop_mae: list[tuple[str, float | None, float | None, int]] = []
    for prop_index, prop_type in enumerate(PROP_TYPES):
        xgb_only = _subset_pairs(holdout, prop_index, shipped[prop_index], headline)
        base_only = [
            (holdout[index].baseline[prop_index].mean, holdout[index].actual[prop_index])
            for index in range(len(holdout))
            if headline[index]
        ]
        prop_mae.append((prop_type, _mae(xgb_only), _mae(base_only), len(xgb_only)))
    long_flag = [not flag for flag in headline]
    long_xgb, long_base, _long_n = collect(long_flag)

    lines = _lines(session)
    xgb_brier_pairs: list[tuple[float, int]] = []
    base_brier_pairs: list[tuple[float, int]] = []
    for index, example in enumerate(holdout):
        if not headline[index]:
            continue
        for prop_index, prop_type in enumerate(PROP_TYPES):
            for line in lines.get((example.player_id, example.game_id, prop_type), []):
                outcome = 1 if example.actual[prop_index] >= line else 0
                center = shipped_mean(shipped[prop_index][index])
                xgb_brier_pairs.append(
                    (probability_at_least(center, spreads[prop_index], line), outcome)
                )
                base_brier_pairs.append(
                    (
                        probability_at_least(
                            example.baseline[prop_index].mean,
                            example.baseline[prop_index].std,
                            line,
                        ),
                        outcome,
                    )
                )
    xgb_brier = brier_score(xgb_brier_pairs) if xgb_brier_pairs else None
    baseline_brier = brier_score(base_brier_pairs) if base_brier_pairs else None
    headline_game_ids = {example.game_id for example in headline_rows}
    label = verdict(
        headline_games=len(headline_game_ids),
        xgb_mae=xgb_mae,
        baseline_mae=baseline_mae,
        xgb_brier=xgb_brier,
        baseline_brier=baseline_brier,
    )

    kalshi_ids = _kalshi_players(session)
    kalshi_flag = [
        headline[index] and holdout[index].player_id in kalshi_ids for index in range(len(holdout))
    ]
    kalshi_xgb, kalshi_base, kalshi_n = collect(kalshi_flag)
    kalshi_game_ids = {
        holdout[index].game_id for index in range(len(holdout)) if kalshi_flag[index]
    }

    _store_holdout(session, holdout, shipped, spreads, contributions)
    session.commit()

    train_dates = len({example.game_date for example in train})
    holdout_dates = len({example.game_date for example in holdout})
    return render_report(
        holdout_on=start,
        train_dates=train_dates,
        holdout_dates=holdout_dates,
        train_rows=len(train),
        holdout_rows=len(holdout),
        headline_games=len(headline_game_ids),
        headline_rows=headline_n,
        xgb_mae=xgb_mae,
        baseline_mae=baseline_mae,
        prop_mae=prop_mae,
        xgb_brier=xgb_brier,
        baseline_brier=baseline_brier,
        brier_contracts=len(xgb_brier_pairs),
        long_gap_rows=len(long_rows) * len(PROP_TYPES),
        long_gap_games=len({example.game_id for example in long_rows}),
        long_xgb_mae=long_xgb,
        long_baseline_mae=long_base,
        label=label,
        kalshi_games=len(kalshi_game_ids),
        kalshi_rows=kalshi_n,
        kalshi_xgb_mae=kalshi_xgb,
        kalshi_baseline_mae=kalshi_base,
    )


def _store_holdout(
    session: Session,
    holdout: Sequence[Example],
    shipped: Sequence[Sequence[float]],
    spreads: Sequence[float],
    contributions: Sequence[Sequence[list[tuple[str, float]]]],
) -> None:
    """Insert holdout rows. An existing (player, game, prop, version) is left as it is."""
    from app.models.baseline import MODEL_VERSION as BASELINE_VERSION

    existing_xgb = _existing(session, MODEL_VERSION)
    existing_base = _existing(session, BASELINE_VERSION)
    inserted_xgb = 0
    inserted_base = 0
    for index, example in enumerate(holdout):
        for prop_index, prop_type in enumerate(PROP_TYPES):
            key = (example.player_id, example.game_id, prop_type)
            if key not in existing_xgb:
                _store_xgb(
                    session,
                    example=example,
                    prop_index=prop_index,
                    mean=shipped[prop_index][index],
                    std=spreads[prop_index],
                    contributions=contributions[prop_index][index],
                    train_std_note=spreads[prop_index],
                )
                inserted_xgb += 1
            if key not in existing_base:
                _store_baseline(session, example, example.baseline[prop_index])
                inserted_base += 1
    logger.info(
        "inserted %d %s rows and %d baseline rows", inserted_xgb, MODEL_VERSION, inserted_base
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Fit the M5 boosters and write the comparison.")
    parser.add_argument("--holdout-fraction", type=float, default=HOLDOUT_FRACTION)
    args = parser.parse_args()
    from app.db.engine import get_engine

    with Session(get_engine()) as session:
        report = run(session, fraction=args.holdout_fraction)
    _RESULTS.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS.write_text(report)
    print(report)
    print(f"wrote {_RESULTS}")


if __name__ == "__main__":
    main()
