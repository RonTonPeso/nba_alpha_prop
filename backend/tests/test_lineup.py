"""Lineup effect apply and starter flag helpers."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session

from app.data.nba import started_from_start_position
from app.db.tables import InjurySignal, Player
from app.models.lineup import EMBIID_ID, MAXEY_ID, adjust_mean
from app.models.lineup_apply import active_out_player_ids, teammate_injured_ids


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


def test_active_out_cleared_by_later_available(db_session: Session) -> None:
    """Newest available/return must clear a prior out (seen before status)."""
    db_session.add(Player(player_id=EMBIID_ID, current_name="Joel Embiid"))
    db_session.commit()
    as_of = datetime(2025, 3, 1, 18, 0, tzinfo=UTC)
    older = as_of - timedelta(days=2)
    newer = as_of - timedelta(hours=1)
    for event_time, claim in ((older, "out"), (newer, "available")):
        db_session.add(
            InjurySignal(
                player_id=EMBIID_ID,
                player_name_raw="Joel Embiid",
                claim_type=claim,
                severity=None,
                expected_games_missed=None,
                source="espn",
                source_reliability_prior=0.7,
                confidence=0.9,
                source_url=f"https://example.com/{claim}",
                raw_text=f"Joel Embiid {claim}",
                event_time=event_time,
                available_at=event_time,
                classifier_model="test",
                prompt_version="test",
                raw_data={},
            )
        )
    db_session.commit()
    assert active_out_player_ids(db_session, as_of=as_of) == []


def test_active_out_keeps_newest_out(db_session: Session) -> None:
    db_session.add(Player(player_id=EMBIID_ID, current_name="Joel Embiid"))
    db_session.commit()
    as_of = datetime(2025, 3, 1, 18, 0, tzinfo=UTC)
    db_session.add(
        InjurySignal(
            player_id=EMBIID_ID,
            player_name_raw="Joel Embiid",
            claim_type="out",
            severity=None,
            expected_games_missed=1.0,
            source="espn",
            source_reliability_prior=0.7,
            confidence=0.9,
            source_url="https://example.com/out-only",
            raw_text="Joel Embiid out",
            event_time=as_of - timedelta(hours=2),
            available_at=as_of - timedelta(hours=2),
            classifier_model="test",
            prompt_version="test",
            raw_data={},
        )
    )
    db_session.commit()
    assert active_out_player_ids(db_session, as_of=as_of) == [EMBIID_ID]


def test_teammate_injured_ids_excludes_opponents() -> None:
    # PHI Maxey beneficiary; Embiid PHI out; Harris listed as opponent out.
    harris_id = 202699
    player_teams = {
        MAXEY_ID: 1610612755,
        EMBIID_ID: 1610612755,
        harris_id: 1610612743,  # other team
    }
    usual = {EMBIID_ID, MAXEY_ID}
    injured = teammate_injured_ids(
        [EMBIID_ID, harris_id],
        beneficiary_id=MAXEY_ID,
        player_teams=player_teams,
        usual_starter_ids=usual,
    )
    assert injured == [EMBIID_ID]


def test_teammate_injured_ids_requires_usual_starter() -> None:
    bench_id = 999001
    player_teams = {MAXEY_ID: 1610612755, bench_id: 1610612755}
    injured = teammate_injured_ids(
        [bench_id],
        beneficiary_id=MAXEY_ID,
        player_teams=player_teams,
        usual_starter_ids={MAXEY_ID},
    )
    assert injured == []
