"""Apply injury signals through lineup effects onto stored forecasts.

Writes ``lineup-m7-v1`` prediction rows. Does not overwrite baseline/xgb/pymc.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc
from sqlmodel import Session, select

from app.data.injury.classify import is_regex_fallback_model
from app.data.starter_backfill import usual_starters_for_team
from app.db.engine import get_engine
from app.db.queries import query_injury_signals
from app.db.tables import Player, PlayerGameLog, Prediction
from app.models.lineup import (
    EMBIID_ID,
    LINEUP_VERSION,
    MAXEY_ID,
    adjust_mean,
    load_effects,
)

logger = logging.getLogger(__name__)

_ACTIVE_CLAIMS = frozenset({"out", "doubtful"})


def player_team_ids_for_game(session: Session, game_id: str) -> dict[int, int]:
    """Map player_id -> team_id for rows logged in ``game_id``."""
    rows = session.exec(
        select(PlayerGameLog.player_id, PlayerGameLog.team_id).where(
            PlayerGameLog.game_id == game_id
        )
    ).all()
    return {int(player_id): int(team_id) for player_id, team_id in rows}


def teammate_injured_ids(
    active_out_ids: list[int],
    *,
    beneficiary_id: int,
    player_teams: dict[int, int],
    usual_starter_ids: set[int],
) -> list[int]:
    """Keep outs that share the beneficiary's team and are usual starters (or self)."""
    team_id = player_teams.get(beneficiary_id)
    if team_id is None:
        return []
    teammates = {pid for pid, tid in player_teams.items() if tid == team_id}
    injured: list[int] = []
    for pid in active_out_ids:
        if pid not in teammates:
            continue
        if pid != beneficiary_id and pid not in usual_starter_ids:
            continue
        injured.append(pid)
    return injured


def active_out_player_ids(
    session: Session,
    *,
    as_of: datetime,
    team_player_ids: set[int] | None = None,
) -> list[int]:
    """Players whose newest signal under the clocks is out/doubtful.

    Signals are newest-first. The first row for each player always marks
    them seen, including available/return/probable, so a later clearing
    claim overrides an earlier out. Only then do we decide active-out.
    """
    signals = query_injury_signals(as_of=as_of, session=session, limit=500)
    out_ids: list[int] = []
    seen: set[int] = set()
    for signal in signals:
        if signal.player_id is None:
            continue
        if signal.player_id in seen:
            continue
        seen.add(signal.player_id)
        if team_player_ids is not None and signal.player_id not in team_player_ids:
            continue
        # Regex / rule fallback is stored for audit but must not arm the trigger.
        if is_regex_fallback_model(signal.classifier_model):
            continue
        if signal.claim_type in _ACTIVE_CLAIMS and signal.confidence >= 0.5:
            out_ids.append(signal.player_id)
    return out_ids


def apply_to_base_prediction(
    session: Session,
    *,
    base: Prediction,
    injured_ids: list[int],
    artifact: dict[str, Any],
    prediction_time: datetime,
) -> Prediction | None:
    """Create or skip a lineup-m7-v1 row from an existing base forecast."""
    existing = session.exec(
        select(Prediction).where(
            Prediction.player_id == base.player_id,
            Prediction.game_id == base.game_id,
            Prediction.prop_type == base.prop_type,
            Prediction.model_version == LINEUP_VERSION,
        )
    ).first()
    if existing is not None:
        return None

    new_mean, applied = adjust_mean(
        base.mean,
        beneficiary_id=base.player_id,
        prop_type=base.prop_type,
        injured_ids=injured_ids,
        artifact=artifact,
    )
    if not applied:
        return None

    std = base.std
    row = Prediction(
        player_id=base.player_id,
        game_id=base.game_id,
        prop_type=base.prop_type,
        model_version=LINEUP_VERSION,
        prediction_time=prediction_time,
        mean=new_mean,
        std=std,
        quantile_10=new_mean - 1.2816 * std,
        quantile_50=new_mean,
        quantile_90=new_mean + 1.2816 * std,
        n_games=base.n_games,
        low_confidence=base.low_confidence or True,
        payload={
            "distribution": "lineup-adjusted",
            "base_model_version": base.model_version,
            "base_mean": base.mean,
            "adjustments": applied,
            "injured_ids": injured_ids,
        },
    )
    session.add(row)
    return row


def apply_lineup_for_game(
    session: Session,
    *,
    game_id: str,
    as_of: datetime | None = None,
    base_version: str = "baseline-m3-v1",
    artifact: dict[str, Any] | None = None,
) -> int:
    as_of = as_of or datetime.now(UTC)
    artifact = artifact or load_effects()
    bases = list(
        session.exec(
            select(Prediction).where(
                Prediction.game_id == game_id,
                Prediction.model_version == base_version,
            )
        ).all()
    )
    if not bases:
        return 0
    player_teams = player_team_ids_for_game(session, game_id)
    # Predictions can exist before tonight's logs; fall back to each player's
    # most recent team_id under the clocks.
    for base in bases:
        if base.player_id in player_teams:
            continue
        recent = session.exec(
            select(PlayerGameLog.team_id)
            .where(PlayerGameLog.player_id == base.player_id)
            .where(PlayerGameLog.event_time < as_of)
            .where(PlayerGameLog.available_at <= as_of)
            .order_by(desc(PlayerGameLog.event_time))  # type: ignore[arg-type]
        ).first()
        if recent is not None:
            player_teams[base.player_id] = int(recent)

    active = active_out_player_ids(session, as_of=as_of)
    usual_cache: dict[int, set[int]] = {}
    written = 0
    for base in bases:
        team_id = player_teams.get(base.player_id)
        if team_id is None:
            continue
        if team_id not in usual_cache:
            usual_cache[team_id] = usual_starters_for_team(session, team_id=team_id, as_of=as_of)
        injured = teammate_injured_ids(
            active,
            beneficiary_id=base.player_id,
            player_teams=player_teams,
            usual_starter_ids=usual_cache[team_id],
        )
        row = apply_to_base_prediction(
            session,
            base=base,
            injured_ids=injured,
            artifact=artifact,
            prediction_time=as_of,
        )
        if row is not None:
            written += 1
    session.commit()
    return written


def run_synthetic_embiid_maxey(
    session: Session,
    *,
    artifact: dict[str, Any] | None = None,
    base_mean: float | None = None,
) -> dict[str, Any]:
    """Acceptance helper: Embiid out should raise Maxey points mean."""
    artifact = artifact or load_effects()
    delta = float(
        artifact.get("effects", {}).get(f"{EMBIID_ID}:{MAXEY_ID}:points", {}).get("delta", 0.0)
    )
    # Floor for the synthetic assert: at least half the fitted effect,
    # and at least 0.5 points when the fit is informative.
    floor = max(0.5, 0.5 * abs(delta)) if delta > 0 else 0.5

    maxey = session.get(Player, MAXEY_ID)
    embiid = session.get(Player, EMBIID_ID)
    if maxey is None or embiid is None:
        return {
            "ok": False,
            "reason": "embiid_or_maxey_missing_from_players",
            "delta": delta,
        }

    if base_mean is None:
        # Prefer a real stored Maxey points forecast; else use a stand-in.
        pred = session.exec(
            select(Prediction)
            .where(
                Prediction.player_id == MAXEY_ID,
                Prediction.prop_type == "points",
            )
            .order_by(desc(Prediction.prediction_time))  # type: ignore[arg-type]
        ).first()
        base_mean = float(pred.mean) if pred is not None else 22.0

    new_mean, applied = adjust_mean(
        base_mean,
        beneficiary_id=MAXEY_ID,
        prop_type="points",
        injured_ids=[EMBIID_ID],
        artifact=artifact,
    )
    # If the historical fit is empty, inject the synthetic effect into a
    # temporary artifact copy only when delta was missing — NO: plan says
    # do not invent a constant. Fail clearly instead.
    embiid_mean, embiid_applied = adjust_mean(
        28.0,
        beneficiary_id=EMBIID_ID,
        prop_type="points",
        injured_ids=[EMBIID_ID],
        artifact=artifact,
    )
    ok = (
        delta > 0
        and (new_mean - base_mean) >= floor
        and embiid_mean == 0.0
        and any(a.get("reason") == "self_out" for a in embiid_applied)
    )
    return {
        "ok": ok,
        "base_mean": base_mean,
        "new_mean": new_mean,
        "lift": new_mean - base_mean,
        "fitted_delta": delta,
        "floor": floor,
        "embiid_mean_after": embiid_mean,
        "applied": applied,
        "model_version": LINEUP_VERSION,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", type=str, default=None)
    parser.add_argument("--synthetic-embiid-maxey", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with Session(get_engine()) as session:
        if args.synthetic_embiid_maxey:
            result = run_synthetic_embiid_maxey(session)
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok") else 1
        if args.game_id:
            n = apply_lineup_for_game(session, game_id=args.game_id)
            print(json.dumps({"game_id": args.game_id, "written": n}, indent=2))
            return 0
    parser.error("pass --game-id or --synthetic-embiid-maxey")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
