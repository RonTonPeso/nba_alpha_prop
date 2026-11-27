"""Unit tests for injury classification and pipeline storage."""

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.data.injury.classify import PROMPT_VERSION, ClassifiedInjury, classify_item
from app.data.injury.pipeline import run_injury_pipeline
from app.data.injury.sources import RawInjuryItem
from app.db.tables import InjurySignal, Player


def test_rule_based_classify_out() -> None:
    item = RawInjuryItem(
        source="espn",
        source_url="https://example.com/embiid-out",
        title="Joel Embiid out vs Knicks",
        text="Joel Embiid out vs Knicks with knee soreness.",
        event_time=datetime(2025, 1, 10, 18, 0, tzinfo=UTC),
        raw_data={},
    )
    # Force rule path.
    import os

    old = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        classified = classify_item(item, allow_rule_fallback=True)
    finally:
        if old is not None:
            os.environ["ANTHROPIC_API_KEY"] = old
    assert classified.claim_type == "out"
    assert "Embiid" in classified.player_name_raw or classified.player_name_raw == ""
    assert classified.prompt_version == PROMPT_VERSION


def test_pipeline_stores_signal(db_session: Session) -> None:
    db_session.add(Player(player_id=203954, current_name="Joel Embiid"))
    db_session.commit()
    item = RawInjuryItem(
        source="espn",
        source_url="https://example.com/unique-embiid-out",
        title="Joel Embiid out tonight",
        text="Joel Embiid out tonight with a knee injury.",
        event_time=datetime(2025, 2, 1, 17, 0, tzinfo=UTC),
        raw_data={},
    )

    def fake_classify(raw: RawInjuryItem) -> ClassifiedInjury:
        from app.data.injury.sources import reliability_for

        return ClassifiedInjury(
            player_name_raw="Joel Embiid",
            claim_type="out",
            severity="knee",
            expected_games_missed=1.0,
            source=raw.source,
            source_reliability_prior=reliability_for(raw.source),
            confidence=0.9,
            source_url=raw.source_url,
            raw_text=raw.text,
            classifier_model="test",
            prompt_version=PROMPT_VERSION,
            raw_data={},
        )

    summary = run_injury_pipeline(
        db_session,
        raw_items=[item],
        classify_fn=fake_classify,
        max_classify=5,
    )
    assert summary.inserted == 1
    row = db_session.exec(select(InjurySignal)).one()
    assert row.player_id == 203954
    assert row.claim_type == "out"


def test_heldout_empty_pred_is_not_player_ok() -> None:
    from app.data.injury.eval_heldout import is_llm_model, player_match

    assert player_match("Joel Embiid", "") is False
    assert player_match("Joel Embiid", "Joel Embiid") is True
    assert player_match("", "Joel Embiid") is False
    assert is_llm_model("rule-based-m7") is False
    assert is_llm_model("claude-haiku-4-5-20251001") is True
