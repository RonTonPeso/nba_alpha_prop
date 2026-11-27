"""M8 dashboard API smoke tests."""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.tables import (
    Game,
    Market,
    MarketSnapshot,
    Player,
    Prediction,
    Team,
)
from app.main import app


def _seed_slate(session: Session) -> None:
    session.add(Team(team_id=1, name="A", city="A", abbreviation="AAA"))
    session.add(Team(team_id=2, name="B", city="B", abbreviation="BBB"))
    session.flush()
    session.add(Player(player_id=203954, current_name="Joel Embiid"))
    session.add(Player(player_id=1630178, current_name="Tyrese Maxey"))
    session.flush()
    game_date = date(2026, 1, 15)
    event = datetime(2026, 1, 16, tzinfo=UTC)
    session.add(
        Game(
            game_id="0022500999",
            season="2025-26",
            season_type="Regular Season",
            game_date=game_date,
            home_team_id=1,
            away_team_id=2,
            event_time=event,
        )
    )
    session.flush()
    now = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    session.add(
        Prediction(
            player_id=1630178,
            game_id="0022500999",
            prop_type="points",
            model_version="baseline-m3-v1",
            prediction_time=now,
            mean=25.0,
            std=6.0,
            quantile_10=17.0,
            quantile_50=25.0,
            quantile_90=33.0,
            n_games=20,
            low_confidence=False,
            payload={"distribution": "residual-normal", "shap_top5": []},
        )
    )
    session.add(
        Market(
            ticker="KXNBAPTS-TEST-MAXEY-25",
            series_ticker="KXNBAPTS",
            event_ticker="KXNBAPTS-TEST",
            prop_type="points",
            line=24.5,
            strike_type="greater",
            open_time=now - timedelta(hours=6),
            close_time=now + timedelta(hours=6),
            title="Tyrese Maxey: 25+ points",
            rules_primary="Tyrese Maxey points",
            kalshi_player_name="Tyrese Maxey",
            kalshi_event_date=game_date,
            kalshi_home_abbr="AAA",
            kalshi_away_abbr="BBB",
            player_id=1630178,
            game_id="0022500999",
            raw_data={},
        )
    )
    session.flush()
    session.add(
        MarketSnapshot(
            ticker="KXNBAPTS-TEST-MAXEY-25",
            quoted_at=now - timedelta(hours=1),
            yes_bid=0.40,
            yes_ask=0.44,
            no_bid=0.56,
            no_ask=0.60,
            status="active",
            raw_data={},
        )
    )
    session.flush()


def test_health() -> None:
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"


def test_comparisons_today_empty_without_db_seed() -> None:
    # Uses real DB via Depends; empty slate still returns 200.
    client = TestClient(app)
    response = client.get("/api/comparisons/today", params={"date": "2099-01-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["rows"] == []


def test_comparisons_and_detail(db_session: Session) -> None:
    _seed_slate(db_session)

    # Override get_session to use the transactional test session.
    from app.db.engine import get_session
    from app.main import app as fastapi_app

    def _override() -> Session:  # type: ignore[misc]
        yield db_session

    fastapi_app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(fastapi_app)
        today = client.get("/api/comparisons/today", params={"date": "2026-01-15"})
        assert today.status_code == 200
        body = today.json()
        assert body["count"] >= 1
        row = body["rows"][0]
        assert row["player_id"] == 1630178
        assert row["prop_type"] == "points"
        assert "gap" in row
        assert "edge" not in row
        assert row["market_mid"] is not None

        detail = client.get(
            "/api/players/1630178/detail",
            params={"game_id": "0022500999", "prop_type": "points"},
        )
        assert detail.status_code == 200
        d = detail.json()
        assert d["player_name"] == "Tyrese Maxey"
        assert d["mean"] == 25.0
        assert len(d["density"]) > 10
        assert "edge" not in d

        status = client.get("/api/status")
        assert status.status_code == 200
        s = status.json()
        assert "injury_rss" in s["job_ids"]
        assert s["scheduler_enabled"] is False

        cal = client.get("/api/calibration/summary")
        assert cal.status_code == 200
        c = cal.json()
        assert "bins" in c
        assert "edge" not in str(c).lower() or "Disagreement" in str(c)
    finally:
        fastapi_app.dependency_overrides.clear()


def test_calibration_summary_parses_reports() -> None:
    client = TestClient(app)
    response = client.get("/api/calibration/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["title"]
    # M4 report should yield bins when docs/results is present.
    assert isinstance(body["bins"], list)
