"""The four ingestion failure modes for the Kalshi source.

Mirrors test_failure_modes.py for M1. Same per-PRD coverage:

1. **Timeout** — cache propagates ``curl_cffi`` ``Timeout``, no row written.
2. **429 rate limit** — cache propagates ``HTTPError``, no row written.
3. **Malformed JSON** — cache propagates the JSON decode error, no row written.
4. **Missing field / upstream schema drift** — ``load_settled_markets``
   skips the malformed market, bumps ``markets_errors``, continues.

The first three live at the network layer (``CachedHttpClient``). The
fourth lives at orchestration (``load_settled_markets``).
"""

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from curl_cffi.requests.exceptions import HTTPError, Timeout
from sqlmodel import Session, select

from app.data.cache import CachedHttpClient, _compute_keys
from app.data.kalshi import fetch_markets_page
from app.data.kalshi_bulk_load import load_settled_markets
from app.db.tables import (
    Game,
    KalshiPlayerAlias,
    Market,
    Player,
    RequestCache,
    Team,
)
from tests._fakes import FakeResponse, FakeSession

_KALSHI_MARKETS_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"


# ----- 1. Timeout -----


def test_kalshi_cache_propagates_timeout_and_does_not_store(db_session: Session) -> None:
    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        raise Timeout("simulated")

    fake = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=fake, max_retries=0)

    with pytest.raises(Timeout):
        fetch_markets_page(cache, series_ticker="KXNBAPTS")

    cache_key, _ = _compute_keys(
        _KALSHI_MARKETS_URL,
        {"series_ticker": "KXNBAPTS", "limit": 200},
    )
    assert db_session.get(RequestCache, cache_key) is None


# ----- 2. 429 rate limit -----


def test_kalshi_cache_propagates_429_and_does_not_store(db_session: Session) -> None:
    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        return FakeResponse(429, {"error": "rate limited"})

    fake = FakeSession(handler)
    # max_retries=0 so we don't sleep through the backoff schedule.
    cache = CachedHttpClient(db_session, client=fake, max_retries=0)

    with pytest.raises(HTTPError):
        fetch_markets_page(cache, series_ticker="KXNBAPTS")

    cache_key, _ = _compute_keys(
        _KALSHI_MARKETS_URL,
        {"series_ticker": "KXNBAPTS", "limit": 200},
    )
    assert db_session.get(RequestCache, cache_key) is None


# ----- 3. Malformed JSON -----


def test_kalshi_cache_propagates_malformed_json_and_does_not_store(db_session: Session) -> None:
    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        return FakeResponse(200, raise_on_json=True)

    fake = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=fake)

    with pytest.raises((json.JSONDecodeError, ValueError)):
        fetch_markets_page(cache, series_ticker="KXNBAPTS")

    cache_key, _ = _compute_keys(
        _KALSHI_MARKETS_URL,
        {"series_ticker": "KXNBAPTS", "limit": 200},
    )
    assert db_session.get(RequestCache, cache_key) is None


# ----- 4. Missing field / upstream schema drift -----


def _seed_minimal_identity(session: Session) -> None:
    session.add(Team(team_id=1610612759, name="Spurs", city="San Antonio", abbreviation="SAS"))
    session.add(Team(team_id=1610612760, name="Thunder", city="Oklahoma City", abbreviation="OKC"))
    session.flush()
    session.add(
        Game(
            game_id="0022500999",
            season="2025-26",
            season_type="Regular Season",
            game_date=date(2026, 5, 30),
            home_team_id=1610612760,
            away_team_id=1610612759,
            event_time=datetime(2026, 5, 31, tzinfo=UTC),
        )
    )
    session.add(Player(player_id=1641705, current_name="Victor Wembanyama"))
    session.flush()
    session.add(KalshiPlayerAlias(kalshi_player_name="Victor Wembanyama", player_id=1641705))
    session.flush()


def _good_market_row() -> dict[str, Any]:
    return {
        "ticker": "KXNBAPTS-26MAY30SASOKC-GOOD-35",
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
        "settlement_ts": "2026-05-31T03:16:20.645898Z",
        "settlement_value_dollars": "0.00",
        "result": "no",
    }


def _bad_market_row_missing_rules() -> dict[str, Any]:
    """Same shape as _good_market_row but missing rules_primary."""
    row = _good_market_row()
    row["ticker"] = "KXNBAPTS-26MAY30SASOKC-BAD-30"
    del row["rules_primary"]
    return row


def test_load_settled_markets_skips_market_with_missing_field(db_session: Session) -> None:
    """One well-formed market + one missing rules_primary. The bad row is
    skipped, the good row inserts, the load completes."""
    _seed_minimal_identity(db_session)

    rows_by_series = {
        "KXNBAPTS": [_good_market_row(), _bad_market_row_missing_rules()],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        series = params.get("series_ticker", "")
        return FakeResponse(200, {"markets": rows_by_series.get(series, []), "cursor": ""})

    fake = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=fake)

    summary = load_settled_markets(cache, db_session)

    assert summary.markets_seen == 2
    assert summary.markets_inserted == 1
    assert summary.markets_errors == 1

    markets = list(db_session.exec(select(Market)).all())
    assert len(markets) == 1
    assert markets[0].ticker == "KXNBAPTS-26MAY30SASOKC-GOOD-35"
