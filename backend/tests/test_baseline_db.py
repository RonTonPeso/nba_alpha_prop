"""Point-in-time tests for storing a baseline forecast.

The future box score is in the database. The forecast at as_of must not
move. A second case covers the sneaky leak: the game already happened,
but ingested_at is after the prediction clock.
"""

from datetime import UTC, date, datetime, timedelta

from sqlmodel import Session, select

from app.db.tables import Game, Market, Player, PlayerGameLog, Prediction, Team
from app.models.baseline import MODEL_VERSION
from app.models.predict import predict_player_game

PLAYER_ID = 999_101
HOME_ID = 999_201
AWAY_ID = 999_202


def _seed_teams(session: Session) -> None:
    session.add(Player(player_id=PLAYER_ID, current_name="Baseline Player"))
    session.add(Team(team_id=HOME_ID, name="Home", city="H", abbreviation="HOM"))
    session.add(Team(team_id=AWAY_ID, name="Away", city="A", abbreviation="AWY"))
    session.flush()


def _add_game(
    session: Session,
    *,
    game_id: str,
    game_date: date,
    home_team_id: int = HOME_ID,
    away_team_id: int = AWAY_ID,
) -> Game:
    game = Game(
        game_id=game_id,
        season="2024-25",
        season_type="Regular Season",
        game_date=game_date,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        event_time=datetime(game_date.year, game_date.month, game_date.day, 23, 0, tzinfo=UTC)
        + timedelta(days=0),
    )
    session.add(game)
    session.flush()
    return game


def _add_log(
    session: Session,
    *,
    game_id: str,
    game_date: date,
    points: int,
    ingested_at: datetime,
    team_id: int = HOME_ID,
) -> None:
    session.add(
        PlayerGameLog(
            player_id=PLAYER_ID,
            game_id=game_id,
            team_id=team_id,
            season="2024-25",
            season_type="Regular Season",
            event_time=datetime(game_date.year, game_date.month, game_date.day, 23, 0, tzinfo=UTC),
            ingested_at=ingested_at,
            points=points,
            rebounds=5,
            assists=4,
        )
    )
    session.flush()


def test_future_game_does_not_change_the_mean(db_session: Session) -> None:
    _seed_teams(db_session)
    # Five visible games at 20 points, every other day in early January.
    for offset in range(5):
        game_date = date(2025, 1, 2) + timedelta(days=offset * 2)
        game_id = f"999_prior_{offset}"
        _add_game(db_session, game_id=game_id, game_date=game_date)
        _add_log(
            db_session,
            game_id=game_id,
            game_date=game_date,
            points=20,
            ingested_at=datetime(2025, 1, 12, 8, 0, tzinfo=UTC),
        )
    # A later game at 100 points. It is in the table. as_of is 16:00 UTC
    # on Jan 20, which is before this game's event_time.
    _add_game(db_session, game_id="999_future", game_date=date(2025, 2, 1))
    _add_log(
        db_session,
        game_id="999_future",
        game_date=date(2025, 2, 1),
        points=100,
        ingested_at=datetime(2025, 2, 2, 8, 0, tzinfo=UTC),
    )
    target = _add_game(db_session, game_id="999_target", game_date=date(2025, 1, 20))

    forecasts, summary = predict_player_game(
        db_session,
        player_id=PLAYER_ID,
        game=target,
        prop_types=("points",),
    )

    assert summary.inserted == 1
    assert len(forecasts) == 1
    assert forecasts[0].mean == 20
    stored = db_session.exec(select(Prediction)).one()
    assert stored.mean == 20
    assert stored.model_version == MODEL_VERSION
    assert stored.prediction_time == datetime(2025, 1, 20, 16, 0, tzinfo=UTC)


def test_late_ingestion_is_invisible(db_session: Session) -> None:
    """The game happened, but we had not ingested it by prediction time."""
    _seed_teams(db_session)
    for offset in range(5):
        game_date = date(2025, 1, 2) + timedelta(days=offset * 2)
        game_id = f"999_known_{offset}"
        _add_game(db_session, game_id=game_id, game_date=game_date)
        _add_log(
            db_session,
            game_id=game_id,
            game_date=game_date,
            points=10,
            ingested_at=datetime(2025, 1, 12, 8, 0, tzinfo=UTC),
        )
    # event_time is Jan 18, before the Jan 20 prediction, but ingested_at is Jan 21.
    _add_game(db_session, game_id="999_late", game_date=date(2025, 1, 18))
    _add_log(
        db_session,
        game_id="999_late",
        game_date=date(2025, 1, 18),
        points=100,
        ingested_at=datetime(2025, 1, 21, 8, 0, tzinfo=UTC),
    )
    target = _add_game(db_session, game_id="999_target_late", game_date=date(2025, 1, 20))

    forecasts, _summary = predict_player_game(
        db_session,
        player_id=PLAYER_ID,
        game=target,
        prop_types=("points",),
    )

    assert forecasts[0].mean == 10


def test_same_version_is_not_written_twice(db_session: Session) -> None:
    _seed_teams(db_session)
    for offset in range(5):
        game_date = date(2025, 1, 2) + timedelta(days=offset * 2)
        game_id = f"999_idem_{offset}"
        _add_game(db_session, game_id=game_id, game_date=game_date)
        _add_log(
            db_session,
            game_id=game_id,
            game_date=game_date,
            points=12,
            ingested_at=datetime(2025, 1, 12, 8, 0, tzinfo=UTC),
        )
    target = _add_game(db_session, game_id="999_idem_target", game_date=date(2025, 1, 20))
    predict_player_game(db_session, player_id=PLAYER_ID, game=target, prop_types=("points",))
    _, second = predict_player_game(
        db_session, player_id=PLAYER_ID, game=target, prop_types=("points",)
    )
    assert second.skipped_existing == 1
    assert second.inserted == 0
    assert len(list(db_session.exec(select(Prediction)).all())) == 1


def test_replay_scores_a_line_without_reading_the_target_as_a_feature(db_session: Session) -> None:
    _seed_teams(db_session)
    for offset in range(5):
        game_date = date(2025, 11, 2) + timedelta(days=offset * 2)
        game_id = f"999_rep_{offset}"
        _add_game(db_session, game_id=game_id, game_date=game_date)
        _add_log(
            db_session,
            game_id=game_id,
            game_date=game_date,
            points=20,
            ingested_at=datetime(2025, 11, 12, 8, 0, tzinfo=UTC),
        )
    _add_game(db_session, game_id="999_rep_target", game_date=date(2025, 11, 20))
    _add_log(
        db_session,
        game_id="999_rep_target",
        game_date=date(2025, 11, 20),
        points=28,
        ingested_at=datetime(2025, 11, 21, 8, 0, tzinfo=UTC),
    )
    db_session.add(
        Market(
            ticker="TEST-PTS-20",
            series_ticker="KXNBAPTS",
            event_ticker="KXNBAPTS-25NOV20",
            prop_type="points",
            line=22.5,
            strike_type="greater",
            open_time=datetime(2025, 11, 20, 12, 0, tzinfo=UTC),
            close_time=datetime(2025, 11, 21, 3, 0, tzinfo=UTC),
            title="Baseline Player: 23+ points",
            rules_primary="If Baseline Player records 23+ points",
            kalshi_player_name="Baseline Player",
            kalshi_event_date=date(2025, 11, 20),
            kalshi_home_abbr="HOM",
            kalshi_away_abbr="AWY",
            player_id=PLAYER_ID,
            game_id="999_rep_target",
            raw_data={},
        )
    )
    db_session.flush()

    from app.backtest.run import replay

    summary = replay(db_session, start=date(2025, 11, 20), end=date(2025, 11, 20))

    assert summary.forecasts == 3  # points, rebounds, assists
    assert summary.mae is not None
    # Points forecast is 20. Actual is 28. The other props are 5 and 4 against themselves.
    assert abs(summary.mae - ((8 + 0 + 0) / 3)) < 1e-9
    assert summary.hits == (0, 1)  # predicted 20 under 22.5, actual 28 over 22.5
    assert len(summary.prob_trials) == 1
    trial = summary.prob_trials[0]
    assert trial.outcome == 1
    assert trial.market_probability is None
    assert trial.probability < 0.5
