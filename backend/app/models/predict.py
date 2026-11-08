"""Turn prior box scores into stored baseline predictions.

Feature reads go through ``query_player_game_logs``, so ``event_time`` and
``available_at`` both have to clear ``as_of``. ``ingested_at`` is the
fetch time and is not the feature clock. The box score of the game
being scored is a label. It is not passed into ``forecast_prop``.

Which team the player is on, for home/away, comes from their most recent
prior game. The schema has no pre-tip roster. Using the outcome log's
team would let a same-day trade leak into the feature. If that prior
team is not in tonight's game, we skip.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlmodel import Session, select

from app.db.queries import query_player_game_logs
from app.db.tables import Game, Market, PlayerGameLog, Prediction
from app.models.baseline import (
    MODEL_VERSION,
    PROP_TYPES,
    Forecast,
    HistoryGame,
    forecast_prop,
    rest_days_between,
)

logger = logging.getLogger(__name__)

# 16:00 UTC is 11:00 ET in the winter and 12:00 ET in the summer.
# The 12:00 UTC ingest has already had four hours to land last night's
# box scores, and NBA tips are still hours away.
PREDICTION_HOUR_UTC = 16
HISTORY_LIMIT = 40


@dataclass
class WriteSummary:
    inserted: int = 0
    skipped_existing: int = 0
    abstained: int = 0
    no_visible_history: int = 0
    short_history: int = 0
    skipped_team: int = 0


def prediction_time_for(game_date: date) -> datetime:
    return datetime(
        game_date.year,
        game_date.month,
        game_date.day,
        PREDICTION_HOUR_UTC,
        0,
        tzinfo=UTC,
    )


def history_before(
    session: Session,
    *,
    player_id: int,
    as_of: datetime,
) -> list[HistoryGame]:
    """Newest-first prior games visible at ``as_of``."""
    logs = query_player_game_logs(
        player_id=player_id,
        as_of=as_of,
        session=session,
        limit=HISTORY_LIMIT,
    )
    if not logs:
        return []
    game_ids = list({log.game_id for log in logs})
    games = session.exec(select(Game).where(Game.game_id.in_(game_ids))).all()  # type: ignore[attr-defined]
    by_id = {game.game_id: game for game in games}
    history: list[HistoryGame] = []
    for log in logs:
        game = by_id.get(log.game_id)
        if game is None:
            continue
        history.append(
            HistoryGame(
                game_date=game.game_date,
                is_home=log.team_id == game.home_team_id,
                team_id=log.team_id,
                points=float(log.points),
                rebounds=float(log.rebounds),
                assists=float(log.assists),
            )
        )
    return history


def _existing(
    session: Session,
    *,
    player_id: int,
    game_id: str,
    prop_type: str,
) -> Prediction | None:
    return session.exec(
        select(Prediction).where(
            Prediction.player_id == player_id,
            Prediction.game_id == game_id,
            Prediction.prop_type == prop_type,
            Prediction.model_version == MODEL_VERSION,
        )
    ).first()


def store_forecast(
    session: Session,
    *,
    player_id: int,
    game_id: str,
    forecast: Forecast,
    prediction_time: datetime,
) -> bool:
    """Insert one row. False when this version was already stored."""
    if (
        _existing(
            session,
            player_id=player_id,
            game_id=game_id,
            prop_type=forecast.prop_type,
        )
        is not None
    ):
        return False
    session.add(
        Prediction(
            player_id=player_id,
            game_id=game_id,
            prop_type=forecast.prop_type,
            model_version=forecast.model_version,
            prediction_time=prediction_time,
            mean=forecast.mean,
            std=forecast.std,
            quantile_10=forecast.quantile_10,
            quantile_50=forecast.quantile_50,
            quantile_90=forecast.quantile_90,
            n_games=forecast.n_games,
            low_confidence=forecast.low_confidence,
            payload=forecast.payload(),
        )
    )
    session.flush()
    return True


def predict_player_game(
    session: Session,
    *,
    player_id: int,
    game: Game,
    prop_types: tuple[str, ...] = PROP_TYPES,
) -> tuple[list[Forecast], WriteSummary]:
    """Forecast one player for one game and store the rows.

    Returns the forecasts that were computed, including ones that already
    existed and were not inserted again.
    """
    summary = WriteSummary()
    as_of = prediction_time_for(game.game_date)
    history = history_before(session, player_id=player_id, as_of=as_of)
    if not history:
        summary.no_visible_history += len(prop_types)
        summary.abstained += len(prop_types)
        return [], summary
    if history[0].team_id not in (game.home_team_id, game.away_team_id):
        summary.skipped_team += len(prop_types)
        return [], summary

    is_home = history[0].team_id == game.home_team_id
    rest_days = rest_days_between(game.game_date, history[0].game_date)
    forecasts: list[Forecast] = []
    for prop_type in prop_types:
        forecast = forecast_prop(
            history,
            prop_type=prop_type,
            is_home=is_home,
            rest_days=rest_days,
        )
        if forecast is None:
            summary.short_history += 1
            summary.abstained += 1
            continue
        forecasts.append(forecast)
        inserted = store_forecast(
            session,
            player_id=player_id,
            game_id=game.game_id,
            forecast=forecast,
            prediction_time=as_of,
        )
        if inserted:
            summary.inserted += 1
        else:
            summary.skipped_existing += 1
    return forecasts, summary


def covered_player_ids(session: Session) -> set[int]:
    """Players a Kalshi market has been resolved to. The M3 population."""
    rows = session.exec(select(Market.player_id).where(Market.player_id.is_not(None))).all()  # type: ignore[union-attr]
    return {int(player_id) for player_id in rows if player_id is not None}


def latest_logs_for_game(session: Session, game_id: str) -> dict[int, PlayerGameLog]:
    """Latest stored box score per player. This is the label, not a feature."""
    logs = session.exec(select(PlayerGameLog).where(PlayerGameLog.game_id == game_id)).all()
    chosen: dict[int, PlayerGameLog] = {}
    for log in logs:
        current = chosen.get(log.player_id)
        if current is None or log.ingested_at >= current.ingested_at:
            chosen[log.player_id] = log
    return chosen


def lines_for(
    session: Session,
    *,
    player_id: int,
    game_id: str,
    prop_type: str,
) -> list[float]:
    markets = session.exec(
        select(Market).where(
            Market.player_id == player_id,
            Market.game_id == game_id,
            Market.prop_type == prop_type,
        )
    ).all()
    return sorted({market.line for market in markets})


def run_daily_predictions(today: date | None = None) -> WriteSummary:
    """Predict today's games for every resolved Kalshi market on those games.

    Opens its own session and commits. ``today`` is overridable in tests.
    """
    today = today or datetime.now(UTC).date()
    summary = WriteSummary()
    from app.db.engine import get_engine

    engine = get_engine()
    with Session(engine) as session:
        games = session.exec(select(Game).where(Game.game_date == today)).all()
        for game in games:
            markets = session.exec(
                select(Market).where(
                    Market.game_id == game.game_id,
                    Market.player_id.is_not(None),  # type: ignore[union-attr]
                )
            ).all()
            seen: set[tuple[int, str]] = set()
            for market in markets:
                if market.player_id is None or market.prop_type not in PROP_TYPES:
                    continue
                key = (market.player_id, market.prop_type)
                if key in seen:
                    continue
                seen.add(key)
                _, part = predict_player_game(
                    session,
                    player_id=market.player_id,
                    game=game,
                    prop_types=(market.prop_type,),
                )
                summary.inserted += part.inserted
                summary.skipped_existing += part.skipped_existing
                summary.abstained += part.abstained
                summary.no_visible_history += part.no_visible_history
                summary.short_history += part.short_history
                summary.skipped_team += part.skipped_team
        session.commit()
    logger.info(
        "Daily predictions %s: inserted=%d skipped=%d abstained=%d team_skip=%d",
        today,
        summary.inserted,
        summary.skipped_existing,
        summary.abstained,
        summary.skipped_team,
    )
    return summary
