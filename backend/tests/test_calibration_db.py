"""The quote used in a replay has to be visible at the prediction clock.

A snapshot whose quoted_at is early enough still stays hidden when
ingested_at is later. last_price does not fill in a missing ask.
"""

from datetime import UTC, date, datetime

from sqlmodel import Session

from app.backtest.quotes import latest_yes_mid
from app.db.tables import Market, MarketSnapshot

AS_OF = datetime(2025, 11, 20, 16, 0, tzinfo=UTC)
TICKER = "TEST-QUOTE-1"


def _market(session: Session) -> None:
    session.add(
        Market(
            ticker=TICKER,
            series_ticker="KXNBAPTS",
            event_ticker="KXNBAPTS-25NOV20",
            prop_type="points",
            line=22.5,
            strike_type="greater",
            open_time=datetime(2025, 11, 20, 12, 0, tzinfo=UTC),
            close_time=datetime(2025, 11, 21, 3, 0, tzinfo=UTC),
            title="Quote Player: 23+ points",
            rules_primary="If Quote Player records 23+ points",
            kalshi_player_name="Quote Player",
            kalshi_event_date=date(2025, 11, 20),
            kalshi_home_abbr="HOM",
            kalshi_away_abbr="AWY",
            raw_data={},
        )
    )
    session.flush()


def _snapshot(
    session: Session,
    *,
    quoted_at: datetime,
    ingested_at: datetime,
    yes_bid: float | None,
    yes_ask: float | None,
    last_price: float | None = 0.99,
) -> None:
    session.add(
        MarketSnapshot(
            ticker=TICKER,
            quoted_at=quoted_at,
            ingested_at=ingested_at,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            last_price=last_price,
            status="active",
            raw_data={},
        )
    )
    session.flush()


def test_later_ingest_hides_an_earlier_quote(db_session: Session) -> None:
    _market(db_session)
    _snapshot(
        db_session,
        quoted_at=datetime(2025, 11, 20, 15, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        yes_bid=0.20,
        yes_ask=0.30,
    )
    assert latest_yes_mid(db_session, TICKER, AS_OF) is None


def test_quote_after_the_clock_is_hidden(db_session: Session) -> None:
    _market(db_session)
    _snapshot(
        db_session,
        quoted_at=datetime(2025, 11, 20, 18, 0, tzinfo=UTC),
        ingested_at=datetime(2025, 11, 20, 18, 0, tzinfo=UTC),
        yes_bid=0.20,
        yes_ask=0.30,
    )
    assert latest_yes_mid(db_session, TICKER, AS_OF) is None


def test_latest_visible_mid_wins_and_ignores_last_price(db_session: Session) -> None:
    _market(db_session)
    _snapshot(
        db_session,
        quoted_at=datetime(2025, 11, 20, 12, 0, tzinfo=UTC),
        ingested_at=datetime(2025, 11, 20, 12, 0, tzinfo=UTC),
        yes_bid=0.10,
        yes_ask=0.20,
        last_price=0.99,
    )
    _snapshot(
        db_session,
        quoted_at=datetime(2025, 11, 20, 15, 0, tzinfo=UTC),
        ingested_at=datetime(2025, 11, 20, 15, 0, tzinfo=UTC),
        yes_bid=0.40,
        yes_ask=0.60,
        last_price=0.01,
    )
    assert latest_yes_mid(db_session, TICKER, AS_OF) == 0.5


def test_one_sided_book_is_not_a_mid(db_session: Session) -> None:
    _market(db_session)
    _snapshot(
        db_session,
        quoted_at=datetime(2025, 11, 20, 15, 0, tzinfo=UTC),
        ingested_at=datetime(2025, 11, 20, 15, 0, tzinfo=UTC),
        yes_bid=0.40,
        yes_ask=None,
        last_price=0.40,
    )
    assert latest_yes_mid(db_session, TICKER, AS_OF) is None
