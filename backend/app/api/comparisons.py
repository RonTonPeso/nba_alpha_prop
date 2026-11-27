"""Build model-vs-market comparison rows for a slate date."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time

from sqlmodel import Session, col, select

from app.api.schemas import ComparisonRow
from app.api.versions import prefer_version
from app.backtest.metrics import probability_at_least
from app.backtest.quotes import latest_yes_mid
from app.db.tables import Game, Market, Player, Prediction

_AS_OF_HOUR_UTC = 16


def slate_as_of(game_date: date) -> datetime:
    """16:00 UTC on the game date — same clock the backtest uses."""
    return datetime.combine(game_date, time(hour=_AS_OF_HOUR_UTC), tzinfo=UTC)


def list_comparison_dates(session: Session, *, limit: int = 60) -> list[date]:
    """Game dates that have at least one prediction joined to a market."""
    rows = session.exec(
        select(col(Game.game_date))
        .join(Prediction, Prediction.game_id == Game.game_id)  # type: ignore[arg-type]
        .join(
            Market,
            (Market.game_id == Prediction.game_id)
            & (Market.player_id == Prediction.player_id)
            & (Market.prop_type == Prediction.prop_type),  # type: ignore[arg-type]
        )
        .distinct()
        .order_by(col(Game.game_date).desc())
        .limit(limit)
    ).all()
    return list(rows)


def default_comparison_date(session: Session) -> date | None:
    dates = list_comparison_dates(session, limit=1)
    return dates[0] if dates else None


def _normal_density(x: float, mean: float, std: float) -> float:
    if std <= 0:
        return 0.0
    z = (x - mean) / std
    return math.exp(-0.5 * z * z) / (std * math.sqrt(2.0 * math.pi))


def density_curve(
    mean: float,
    std: float,
    *,
    n: int = 60,
) -> list[dict[str, float]]:
    """Sample a normal density for the player-detail chart."""
    width = max(std * 4.0, 1.0)
    lo = max(0.0, mean - width)
    hi = mean + width
    if hi <= lo:
        hi = lo + 1.0
    step = (hi - lo) / max(n - 1, 1)
    points: list[dict[str, float]] = []
    for i in range(n):
        x = lo + i * step
        points.append({"x": x, "density": _normal_density(x, mean, std)})
    return points


def build_comparisons_for_date(
    session: Session,
    *,
    game_date: date,
    limit: int = 100,
) -> list[ComparisonRow]:
    as_of = slate_as_of(game_date)
    games = session.exec(select(Game).where(Game.game_date == game_date)).all()
    if not games:
        return []
    game_ids = {g.game_id for g in games}
    game_by_id = {g.game_id: g for g in games}

    predictions = session.exec(
        select(Prediction).where(col(Prediction.game_id).in_(game_ids))
    ).all()
    if not predictions:
        return []

    # Prefer one version per (player, game, prop).
    by_key: dict[tuple[int, str, str], dict[str, Prediction]] = {}
    for pred in predictions:
        key = (pred.player_id, pred.game_id, pred.prop_type)
        by_key.setdefault(key, {})[pred.model_version] = pred

    chosen: list[Prediction] = []
    for versions in by_key.values():
        pick = prefer_version(set(versions))
        if pick is None:
            continue
        chosen.append(versions[pick])

    player_ids = {p.player_id for p in chosen}
    players = {
        p.player_id: p
        for p in session.exec(select(Player).where(col(Player.player_id).in_(player_ids))).all()
    }

    markets = session.exec(
        select(Market).where(
            col(Market.game_id).in_(game_ids),
            Market.player_id.is_not(None),  # type: ignore[union-attr]
        )
    ).all()
    markets_by_key: dict[tuple[int, str, str], list[Market]] = {}
    for market in markets:
        if market.player_id is None or market.game_id is None:
            continue
        key = (market.player_id, market.game_id, market.prop_type)
        markets_by_key.setdefault(key, []).append(market)

    rows: list[ComparisonRow] = []
    for pred in chosen:
        game = game_by_id.get(pred.game_id)
        if game is None:
            continue
        player = players.get(pred.player_id)
        name = player.current_name if player else str(pred.player_id)
        market_list = markets_by_key.get((pred.player_id, pred.game_id, pred.prop_type), [])
        if not market_list:
            continue
        for market in market_list:
            try:
                model_p = probability_at_least(pred.mean, pred.std, market.line)
            except ValueError:
                continue
            mid = latest_yes_mid(session, market.ticker, as_of)
            # If no pre-tip mid, try the latest snapshot without as_of filter
            # for dashboard display only (labeled via null mid if still missing).
            if mid is None:
                mid = latest_yes_mid(
                    session,
                    market.ticker,
                    datetime.now(UTC),
                )
            gap = (model_p - mid) if mid is not None else None
            rows.append(
                ComparisonRow(
                    player_id=pred.player_id,
                    player_name=name,
                    game_id=pred.game_id,
                    game_date=game.game_date,
                    prop_type=pred.prop_type,
                    line=market.line,
                    model_version=pred.model_version,
                    model_p=model_p,
                    market_mid=mid,
                    gap=gap,
                    low_confidence=pred.low_confidence,
                    mean=pred.mean,
                    std=pred.std,
                )
            )

    rows.sort(key=lambda r: abs(r.gap) if r.gap is not None else -1.0, reverse=True)
    return rows[:limit]


def available_prop_types(session: Session, player_id: int, game_id: str) -> list[str]:
    rows = session.exec(
        select(Prediction.prop_type)
        .where(Prediction.player_id == player_id, Prediction.game_id == game_id)
        .distinct()
    ).all()
    return sorted(rows)
