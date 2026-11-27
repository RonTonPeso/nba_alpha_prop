"""Lineup effect apply and starter flag helpers."""

from typing import Any

from app.data.nba import started_from_start_position
from app.models.lineup import EMBIID_ID, MAXEY_ID, adjust_mean


def test_started_from_start_position() -> None:
    assert started_from_start_position("C") is True
    assert started_from_start_position("F") is True
    assert started_from_start_position("") is False
    assert started_from_start_position(None) is False
    assert started_from_start_position("  ") is False


def test_adjust_mean_self_out_zeros() -> None:
    artifact: dict[str, Any] = {"effects": {}}
    mean, applied = adjust_mean(
        28.0,
        beneficiary_id=EMBIID_ID,
        prop_type="points",
        injured_ids=[EMBIID_ID],
        artifact=artifact,
    )
    assert mean == 0.0
    assert applied[0]["reason"] == "self_out"


def test_adjust_mean_teammate_shift() -> None:
    artifact: dict[str, Any] = {
        "effects": {
            f"{EMBIID_ID}:{MAXEY_ID}:points": {
                "injured_id": EMBIID_ID,
                "beneficiary_id": MAXEY_ID,
                "prop_type": "points",
                "delta": 4.5,
            }
        }
    }
    mean, applied = adjust_mean(
        22.0,
        beneficiary_id=MAXEY_ID,
        prop_type="points",
        injured_ids=[EMBIID_ID],
        artifact=artifact,
    )
    assert mean == 26.5
    assert applied[0]["delta"] == 4.5
