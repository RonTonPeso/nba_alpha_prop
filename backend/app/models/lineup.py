"""Lineup-conditional redistribution: teammate shifts when a starter is out.

Effects are estimated from historical games with ``started`` flags, then
applied when an injury signal says a usual starter is out or doubtful.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, col, select

from app.data.starter_backfill import USUAL_STARTER_MIN_STARTS, USUAL_STARTER_WINDOW
from app.db.tables import Game, PlayerGameLog

logger = logging.getLogger(__name__)

LINEUP_VERSION = "lineup-m7-v1"
PROP_TYPES = ("points", "rebounds", "assists")
_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ARTIFACT = _ROOT / "models" / "lineup_m7_effects.json"

# Embiid / Maxey NBA IDs (stable).
EMBIID_ID = 203954
MAXEY_ID = 1630178


@dataclass
class EffectEstimate:
    delta: float
    n_out: int
    n_in: int
    mean_out: float
    mean_in: float


def _stat_for(row: PlayerGameLog, prop_type: str) -> float:
    if prop_type == "points":
        return float(row.points)
    if prop_type == "rebounds":
        return float(row.rebounds)
    if prop_type == "assists":
        return float(row.assists)
    raise ValueError(prop_type)


def _usual_starters_from_history(
    history: list[tuple[str, dict[int, bool]]],
    *,
    window: int,
    min_starts: int,
) -> set[int]:
    """``history`` is newest-first list of (game_id, player_id -> started)."""
    window_games = history[:window]
    if not window_games:
        return set()
    counts: dict[int, int] = defaultdict(int)
    for _game_id, started_map in window_games:
        for player_id, started in started_map.items():
            if started:
                counts[player_id] += 1
    return {pid for pid, n in counts.items() if n >= min_starts}


def fit_lineup_effects(
    session: Session,
    *,
    as_of: datetime | None = None,
    props: tuple[str, ...] = PROP_TYPES,
    min_out_games: int = 3,
    shrink_k: float = 8.0,
) -> dict[str, Any]:
    """Estimate shrunk mean deltas for (injured, beneficiary, prop).

    Loads all starter-flagged logs once, then walks each team timeline.
    """
    as_of = as_of or datetime.now(UTC)
    games = {
        g.game_id: g
        for g in session.exec(
            select(Game).where(Game.event_time < as_of).order_by(col(Game.game_date))
        ).all()
    }
    logs = list(
        session.exec(
            select(PlayerGameLog)
            .where(PlayerGameLog.event_time < as_of)
            .where(PlayerGameLog.available_at <= as_of)
            .where(PlayerGameLog.started.is_not(None))  # type: ignore[union-attr]
        ).all()
    )

    # team_id -> list of (event_time, game_id, rows)
    by_team_game: dict[int, dict[str, list[PlayerGameLog]]] = defaultdict(lambda: defaultdict(list))
    for row in logs:
        by_team_game[row.team_id][row.game_id].append(row)

    out_vals: dict[tuple[int, int, str], list[float]] = defaultdict(list)
    in_vals: dict[tuple[int, int, str], list[float]] = defaultdict(list)

    # Sparse opponent timelines (e.g. only games vs a PHI-only backfill) are
    # not enough history to estimate teammate effects; skip them.
    min_team_games = 20

    for _team_id, game_map in by_team_game.items():
        # Chronological team games that have starter flags.
        ordered: list[tuple[datetime, str, list[PlayerGameLog]]] = []
        for game_id, rows in game_map.items():
            game = games.get(game_id)
            if game is None:
                continue
            ordered.append((game.event_time, game_id, rows))
        ordered.sort(key=lambda t: t[0])
        if len(ordered) < min_team_games:
            continue

        # Build newest-first started maps after each game for usual-starter lookback.
        started_history: list[tuple[str, dict[int, bool]]] = []
        for _event_time, game_id, rows in ordered:
            started_map = {r.player_id: bool(r.started) for r in rows}
            # Prior history only (exclude tonight).
            usual = _usual_starters_from_history(
                list(reversed(started_history)),
                window=USUAL_STARTER_WINDOW,
                min_starts=USUAL_STARTER_MIN_STARTS,
            )
            appeared = {r.player_id for r in rows}
            started_ids = {r.player_id for r in rows if r.started}
            # Require the player on tonight's team log so traded/departed
            # usual starters are not labeled "out" for several games after leaving.
            out_ids = {pid for pid in usual if pid not in started_ids and pid in appeared}

            playing = [r for r in rows if r.minutes is not None and r.minutes > 0]
            for injured_id in out_ids:
                for row in playing:
                    if row.player_id == injured_id:
                        continue
                    for prop in props:
                        out_vals[(injured_id, row.player_id, prop)].append(_stat_for(row, prop))
            for injured_id in started_ids:
                for row in playing:
                    if row.player_id == injured_id:
                        continue
                    for prop in props:
                        in_vals[(injured_id, row.player_id, prop)].append(_stat_for(row, prop))

            started_history.append((game_id, started_map))

    effects: dict[str, dict[str, Any]] = {}
    for key, outs in out_vals.items():
        injured_id, beneficiary_id, prop = key
        ins = in_vals.get(key, [])
        n_out = len(outs)
        n_in = len(ins)
        if n_out < min_out_games or n_in < min_out_games:
            continue
        mean_out = sum(outs) / n_out
        mean_in = sum(ins) / n_in
        raw = mean_out - mean_in
        weight = n_out / (n_out + shrink_k)
        delta = raw * weight
        effect_key = f"{injured_id}:{beneficiary_id}:{prop}"
        effects[effect_key] = {
            "injured_id": injured_id,
            "beneficiary_id": beneficiary_id,
            "prop_type": prop,
            "delta": delta,
            "raw_delta": raw,
            "n_out": n_out,
            "n_in": n_in,
            "mean_out": mean_out,
            "mean_in": mean_in,
        }

    return {
        "model_version": LINEUP_VERSION,
        "as_of": as_of.isoformat(),
        "window": USUAL_STARTER_WINDOW,
        "min_starts": USUAL_STARTER_MIN_STARTS,
        "min_out_games": min_out_games,
        "shrink_k": shrink_k,
        "n_effects": len(effects),
        "n_flagged_logs": len(logs),
        "effects": effects,
    }


def save_effects(artifact: dict[str, Any], path: Path | None = None) -> Path:
    path = path or _DEFAULT_ARTIFACT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2) + "\n")
    return path


def load_effects(path: Path | None = None) -> dict[str, Any]:
    path = path or _DEFAULT_ARTIFACT
    loaded: Any = json.loads(path.read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"lineup effects artifact must be an object: {path}")
    return loaded


def lookup_delta(
    artifact: dict[str, Any],
    *,
    injured_id: int,
    beneficiary_id: int,
    prop_type: str,
) -> float:
    key = f"{injured_id}:{beneficiary_id}:{prop_type}"
    effect = artifact.get("effects", {}).get(key)
    if effect is None:
        return 0.0
    return float(effect["delta"])


def adjust_mean(
    base_mean: float,
    *,
    beneficiary_id: int,
    prop_type: str,
    injured_ids: list[int],
    artifact: dict[str, Any],
) -> tuple[float, list[dict[str, Any]]]:
    """Apply additive teammate shifts for each injured starter."""
    applied: list[dict[str, Any]] = []
    mean = base_mean
    for injured_id in injured_ids:
        if injured_id == beneficiary_id:
            applied.append(
                {
                    "injured_id": injured_id,
                    "delta": -base_mean,
                    "reason": "self_out",
                }
            )
            mean = 0.0
            continue
        delta = lookup_delta(
            artifact,
            injured_id=injured_id,
            beneficiary_id=beneficiary_id,
            prop_type=prop_type,
        )
        if delta == 0.0:
            continue
        mean += delta
        applied.append(
            {
                "injured_id": injured_id,
                "delta": delta,
                "reason": "teammate_out",
            }
        )
    return mean, applied
