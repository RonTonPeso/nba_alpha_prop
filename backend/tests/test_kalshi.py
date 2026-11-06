"""Tests for the Kalshi NBA prop client (fetcher + parsers).

Mirrors test_nba.py shape: small unit tests for parser helpers, a
round-trip test that exercises the fetcher + cache + FakeSession, and
a pagination test for iter_markets.
"""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlmodel import Session

from app.data.cache import CachedHttpClient
from app.data.kalshi import (
    _parse_event_ticker,
    _parse_kalshi_date,
    _parse_player_from_rules,
    fetch_markets_page,
    iter_markets,
    market_row_to_orm,
    market_row_to_settlement,
    market_row_to_snapshot,
)
from tests._fakes import FakeResponse, FakeSession

# ---------- parser helpers ----------


def test_parse_kalshi_date_various() -> None:
    assert _parse_kalshi_date("26MAY30") == date(2026, 5, 30)
    assert _parse_kalshi_date("25NOV01") == date(2025, 11, 1)
    assert _parse_kalshi_date("00JAN01") == date(2000, 1, 1)
    assert _parse_kalshi_date("99DEC31") == date(1999, 12, 31)


def test_parse_kalshi_date_rejects_bad_month() -> None:
    with pytest.raises(ValueError, match="Unknown month"):
        _parse_kalshi_date("26XYZ30")


def test_parse_kalshi_date_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="not 7 chars"):
        _parse_kalshi_date("26MAY3")


def test_parse_event_ticker_happy_path() -> None:
    series, d, away, home = _parse_event_ticker("KXNBAPTS-26MAY30SASOKC")
    assert series == "KXNBAPTS"
    assert d == date(2026, 5, 30)
    assert away == "SAS"
    assert home == "OKC"


def test_parse_event_ticker_rejects_malformed() -> None:
    with pytest.raises(ValueError, match="SERIES-DATEGAMES"):
        _parse_event_ticker("KXNBAPTS")
    with pytest.raises(ValueError, match="expected 13 chars"):
        _parse_event_ticker("KXNBAPTS-26MAY30SAS")  # missing home abbr


def test_parse_player_from_rules() -> None:
    rules = (
        "If Victor Wembanyama records 35+ Points in the San Antonio vs "
        "Oklahoma City professional basketball game originally scheduled "
        "for May 30, 2026, then the market resolves to Yes."
    )
    assert _parse_player_from_rules(rules) == "Victor Wembanyama"

    # Hyphens, apostrophes, periods in names.
    rules2 = "If Shai Gilgeous-Alexander records 30+ Points in the game..."
    assert _parse_player_from_rules(rules2) == "Shai Gilgeous-Alexander"

    rules3 = "If De'Aaron Fox records 25+ Points in the game..."
    assert _parse_player_from_rules(rules3) == "De'Aaron Fox"


def test_parse_player_from_rules_rejects_unmatched() -> None:
    with pytest.raises(ValueError, match="doesn't match"):
        _parse_player_from_rules("Some other prefix that doesn't start with If...")


# ---------- ORM converters ----------


def _sample_market() -> dict[str, Any]:
    """A pared-down Kalshi market dict, real-shape from our probe."""
    return {
        "ticker": "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35",
        "event_ticker": "KXNBAPTS-26MAY30SASOKC",
        "title": "Victor Wembanyama: 35+ points",
        "rules_primary": (
            "If Victor Wembanyama records 35+ Points in the San Antonio "
            "vs Oklahoma City professional basketball game originally "
            "scheduled for May 30, 2026, then the market resolves to Yes."
        ),
        "floor_strike": 34.5,
        "strike_type": "structured",
        "open_time": "2026-05-29T04:10:00Z",
        "close_time": "2026-05-31T03:10:13Z",
        "status": "finalized",
        "result": "no",
        "settlement_ts": "2026-05-31T03:16:20.645898Z",
        "settlement_value_dollars": "0.0000",
        "updated_time": "2026-05-31T03:16:20.7Z",
        "yes_bid_dollars": "0.0200",
        "yes_ask_dollars": "0.0500",
        "no_bid_dollars": "0.9500",
        "no_ask_dollars": "0.9800",
        "last_price_dollars": "0.0100",
        "volume_fp": "500.00",
        "volume_24h_fp": "120.00",
        "open_interest_fp": "300.00",
        "liquidity_dollars": "10.5",
    }


def test_market_row_to_orm_populates_all_fields() -> None:
    m = market_row_to_orm(_sample_market())
    assert m.ticker == "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35"
    assert m.series_ticker == "KXNBAPTS"
    assert m.event_ticker == "KXNBAPTS-26MAY30SASOKC"
    assert m.prop_type == "points"
    assert m.line == 34.5
    assert m.strike_type == "structured"
    assert m.open_time == datetime(2026, 5, 29, 4, 10, tzinfo=UTC)
    assert m.kalshi_player_name == "Victor Wembanyama"
    assert m.kalshi_event_date == date(2026, 5, 30)
    assert m.kalshi_away_abbr == "SAS"
    assert m.kalshi_home_abbr == "OKC"
    # FKs are NOT resolved by the parser.
    assert m.player_id is None
    assert m.game_id is None
    # raw_data preserves the source for re-resolution later.
    assert m.raw_data["ticker"] == "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35"


def test_market_row_to_orm_rejects_unknown_series() -> None:
    row = _sample_market()
    row["event_ticker"] = "KXNBA3PT-26MAY30SASOKC"  # threes, out of scope
    with pytest.raises(ValueError, match="Unrecognized series"):
        market_row_to_orm(row)


def test_market_row_to_orm_maps_rebounds_and_assists() -> None:
    pts = _sample_market()
    pts["event_ticker"] = "KXNBAREB-26MAY30SASOKC"
    pts["ticker"] = "KXNBAREB-..."
    assert market_row_to_orm(pts).prop_type == "rebounds"

    ast = _sample_market()
    ast["event_ticker"] = "KXNBAAST-26MAY30SASOKC"
    ast["ticker"] = "KXNBAAST-..."
    assert market_row_to_orm(ast).prop_type == "assists"


def test_market_row_to_snapshot_uses_updated_time() -> None:
    s = market_row_to_snapshot(_sample_market())
    assert s.quoted_at == datetime(2026, 5, 31, 3, 16, 20, 700_000, tzinfo=UTC)
    assert s.yes_bid == 0.02
    assert s.yes_ask == 0.05
    assert s.no_bid == 0.95
    assert s.no_ask == 0.98
    assert s.last_price == 0.01
    assert s.volume == 500.0
    assert s.volume_24h == 120.0
    assert s.open_interest == 300.0
    assert s.liquidity == 10.5
    assert s.status == "finalized"


def test_market_row_to_snapshot_falls_back_to_now_when_no_updated_time() -> None:
    row = _sample_market()
    row.pop("updated_time")
    before = datetime.now(UTC)
    s = market_row_to_snapshot(row)
    after = datetime.now(UTC)
    assert before <= s.quoted_at <= after


def test_market_row_to_snapshot_tolerates_missing_price_fields() -> None:
    row = _sample_market()
    for k in [
        "yes_bid_dollars",
        "yes_ask_dollars",
        "no_bid_dollars",
        "no_ask_dollars",
        "last_price_dollars",
        "volume_fp",
        "open_interest_fp",
        "liquidity_dollars",
    ]:
        row.pop(k)
    s = market_row_to_snapshot(row)
    assert s.yes_bid is None
    assert s.yes_ask is None
    assert s.no_bid is None
    assert s.last_price is None
    assert s.volume is None


def test_market_row_to_settlement_returns_row_when_finalized() -> None:
    settlement = market_row_to_settlement(_sample_market())
    assert settlement is not None
    assert settlement.ticker == "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35"
    assert settlement.result == "no"
    assert settlement.settlement_value == 0.0
    assert settlement.settled_at == datetime(2026, 5, 31, 3, 16, 20, 645898, tzinfo=UTC)


def test_market_row_to_settlement_returns_none_when_unsettled() -> None:
    row = _sample_market()
    row.pop("settlement_ts")
    row["result"] = ""
    assert market_row_to_settlement(row) is None

    row2 = _sample_market()
    row2["result"] = "pending"  # not "yes" or "no"
    assert market_row_to_settlement(row2) is None


# ---------- fetcher + pagination ----------


def test_fetch_markets_page_round_trip_via_cache(db_session: Session) -> None:
    """Round trip: fetcher hits the API once, cache serves the repeat."""
    body = {"markets": [_sample_market()], "cursor": ""}

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        assert url.endswith("/markets")
        assert params["series_ticker"] == "KXNBAPTS"
        assert params["status"] == "settled"
        assert params["limit"] == 50
        return FakeResponse(200, body)

    fake = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=fake)

    body1 = fetch_markets_page(cache, series_ticker="KXNBAPTS", status="settled", limit=50)
    assert body1 == body
    assert fake.call_count == 1

    # Second call same params: served from cache, no extra network.
    body2 = fetch_markets_page(cache, series_ticker="KXNBAPTS", status="settled", limit=50)
    assert body2 == body
    assert fake.call_count == 1


def test_iter_markets_paginates_and_stops_on_empty_cursor(db_session: Session) -> None:
    """Two pages: page 1 returns cursor 'p2'; page 2 returns no cursor."""
    page1 = {"markets": [{"id": 1}, {"id": 2}], "cursor": "p2"}
    page2 = {"markets": [{"id": 3}], "cursor": ""}

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        if params.get("cursor") == "p2":
            return FakeResponse(200, page2)
        return FakeResponse(200, page1)

    fake = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=fake)

    rows = list(iter_markets(cache, series_ticker="KXNBAPTS", page_size=2))
    assert [r["id"] for r in rows] == [1, 2, 3]
    assert fake.call_count == 2


def test_iter_markets_stops_on_empty_page(db_session: Session) -> None:
    """An empty markets array terminates the loop even if cursor is present."""
    empty = {"markets": [], "cursor": "should-not-follow"}

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        return FakeResponse(200, empty)

    fake = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=fake)

    rows = list(iter_markets(cache, series_ticker="KXNBAPTS"))
    assert rows == []
    assert fake.call_count == 1
