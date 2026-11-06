"""Tests for the Kalshi bulk load orchestration.

Covers: alias resolution (player + game), unmapped fallthrough,
idempotency, settlement insertion only for finalized markets, and
backfilling FKs on re-run after the alias table grows.
"""

from datetime import UTC, date, datetime
from typing import Any

from sqlmodel import Session, select

from app.data.cache import CachedHttpClient
from app.data.kalshi_bulk_load import load_settled_markets
from app.db.tables import (
    Game,
    KalshiPlayerAlias,
    Market,
    MarketSettlement,
    Player,
    Team,
)
from tests._fakes import FakeResponse, FakeSession

# ---------- seeding helpers ----------


def _seed_identity(session: Session) -> None:
    """Two teams + one game between them. Game on 2026-05-30, SAS @ OKC.

    The synthetic Kalshi market in `_synthetic_market_row` targets this
    game so the alias resolution path can find a match.
    """
    session.add(Team(team_id=1610612759, name="Spurs", city="San Antonio", abbreviation="SAS"))
    session.add(Team(team_id=1610612760, name="Thunder", city="Oklahoma City", abbreviation="OKC"))
    session.flush()
    session.add(
        Game(
            game_id="0022500999",
            season="2025-26",
            season_type="Regular Season",
            game_date=date(2026, 5, 30),
            home_team_id=1610612760,  # OKC home
            away_team_id=1610612759,  # SAS away
            event_time=datetime(2026, 5, 31, tzinfo=UTC),
        )
    )
    session.add(Player(player_id=1641705, current_name="Victor Wembanyama"))
    session.add(Player(player_id=1628983, current_name="Shai Gilgeous-Alexander"))
    session.flush()


def _add_alias(session: Session, name: str, player_id: int) -> None:
    session.add(KalshiPlayerAlias(kalshi_player_name=name, player_id=player_id))
    session.flush()


def _synthetic_market_row(
    *,
    ticker: str,
    series_ticker: str = "KXNBAPTS",
    player_name: str = "Victor Wembanyama",
    line: float = 34.5,
    result: str = "no",
    settlement_ts: str | None = "2026-05-31T03:16:20.645898Z",
    away_abbr: str = "SAS",
    home_abbr: str = "OKC",
    event_date_str: str = "26MAY30",
) -> dict[str, Any]:
    event_ticker = f"{series_ticker}-{event_date_str}{away_abbr}{home_abbr}"
    row: dict[str, Any] = {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "title": f"{player_name}: line {line}",
        "rules_primary": (
            f"If {player_name} records {int(line) + 1}+ Points in the "
            f"X vs Y professional basketball game originally scheduled "
            f"for May 30, 2026, then the market resolves to Yes."
        ),
        "floor_strike": line,
        "strike_type": "structured",
        "open_time": "2026-05-29T04:10:00Z",
        "close_time": "2026-05-31T03:10:13Z",
        "status": "finalized" if settlement_ts else "active",
        "updated_time": "2026-05-31T03:16:20.7Z",
        "yes_bid_dollars": "0.02",
        "yes_ask_dollars": "0.05",
        "no_bid_dollars": "0.95",
        "no_ask_dollars": "0.98",
        "last_price_dollars": "0.01",
        "volume_fp": "500.00",
        "volume_24h_fp": "120.00",
        "open_interest_fp": "300.00",
        "liquidity_dollars": "10.5",
    }
    if settlement_ts:
        row["settlement_ts"] = settlement_ts
        row["settlement_value_dollars"] = "0.00" if result == "no" else "1.00"
        row["result"] = result
    return row


def _make_handler(
    rows_by_series: dict[str, list[dict[str, Any]]],
) -> Any:
    """Returns a FakeSession handler that paginates a per-series list of rows."""

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        series = params.get("series_ticker", "")
        rows = rows_by_series.get(series, [])
        # Single-page response (no cursor).
        return FakeResponse(200, {"markets": rows, "cursor": ""})

    return handler


# ---------- happy path ----------


def test_load_round_trip_with_full_alias_resolution(db_session: Session) -> None:
    """Both player and game aliases resolve; market + settlement inserted."""
    _seed_identity(db_session)
    _add_alias(db_session, "Victor Wembanyama", 1641705)

    rows = {
        "KXNBAPTS": [
            _synthetic_market_row(ticker="KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35", line=34.5)
        ],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    summary = load_settled_markets(cache, db_session)

    assert summary.markets_seen == 1
    assert summary.markets_inserted == 1
    assert summary.settlements_inserted == 1
    assert summary.players_resolved == 1
    assert summary.games_resolved == 1
    assert summary.players_unmapped == 0
    assert summary.games_unmapped == 0

    market = db_session.get(Market, "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35")
    assert market is not None
    assert market.player_id == 1641705
    assert market.game_id == "0022500999"
    assert market.prop_type == "points"

    settlement = db_session.get(MarketSettlement, "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35")
    assert settlement is not None
    assert settlement.result == "no"
    assert settlement.settlement_value == 0.0


# ---------- unmapped alias paths ----------


def test_load_inserts_market_with_null_player_id_when_alias_missing(
    db_session: Session,
) -> None:
    """No alias row for the player; market still inserts with NULL FK."""
    _seed_identity(db_session)
    # NOTE: not adding the alias.

    rows = {
        "KXNBAPTS": [
            _synthetic_market_row(ticker="KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35", line=34.5)
        ],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    summary = load_settled_markets(cache, db_session)

    assert summary.markets_inserted == 1
    assert summary.players_unmapped == 1
    assert "Victor Wembanyama" in summary.unmapped_player_names

    market = db_session.get(Market, "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35")
    assert market is not None
    assert market.player_id is None
    assert market.game_id == "0022500999"  # game resolution worked


def test_load_inserts_market_with_null_game_id_when_game_unknown(
    db_session: Session,
) -> None:
    """Kalshi event_ticker date/abbrs don't match any M1 game."""
    _seed_identity(db_session)
    _add_alias(db_session, "Victor Wembanyama", 1641705)

    # Date 2026-12-25 is not in our seeded games.
    rows = {
        "KXNBAPTS": [
            _synthetic_market_row(
                ticker="KXNBAPTS-26DEC25SASOKC-SASVWEMBANYAMA1-35",
                event_date_str="26DEC25",
            )
        ],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    summary = load_settled_markets(cache, db_session)

    assert summary.markets_inserted == 1
    assert summary.games_unmapped == 1
    assert summary.players_resolved == 1  # player still resolves

    market = db_session.get(Market, "KXNBAPTS-26DEC25SASOKC-SASVWEMBANYAMA1-35")
    assert market is not None
    assert market.game_id is None
    assert market.player_id == 1641705


# ---------- idempotency + backfill ----------


def test_load_is_idempotent(db_session: Session) -> None:
    """Re-running with the same data inserts zero new rows."""
    _seed_identity(db_session)
    _add_alias(db_session, "Victor Wembanyama", 1641705)

    rows = {
        "KXNBAPTS": [_synthetic_market_row(ticker="KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35")],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    load_settled_markets(cache, db_session)
    network_calls_after_first = fake.call_count

    summary2 = load_settled_markets(cache, db_session)
    assert summary2.markets_inserted == 0
    assert summary2.markets_skipped == 1
    assert summary2.settlements_inserted == 0
    assert summary2.settlements_skipped == 1
    # Cache served the second pass (one call per series_ticker, all 3 cached).
    assert fake.call_count == network_calls_after_first

    assert len(list(db_session.exec(select(Market)).all())) == 1
    assert len(list(db_session.exec(select(MarketSettlement)).all())) == 1


def test_load_backfills_null_fks_on_rerun_after_alias_added(db_session: Session) -> None:
    """First run: no alias -> NULL player_id. Add alias. Second run: backfilled."""
    _seed_identity(db_session)
    # No alias initially.

    rows = {
        "KXNBAPTS": [_synthetic_market_row(ticker="KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35")],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    load_settled_markets(cache, db_session)
    market = db_session.get(Market, "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35")
    assert market is not None
    assert market.player_id is None

    # Add the alias and re-run. Same cache, same fake.
    _add_alias(db_session, "Victor Wembanyama", 1641705)
    summary = load_settled_markets(cache, db_session)

    assert summary.markets_inserted == 0  # already exists
    assert summary.players_resolved == 1  # backfilled

    db_session.refresh(market)
    assert market.player_id == 1641705


# ---------- settlement gating ----------


def test_load_does_not_write_settlement_for_unsettled_market(
    db_session: Session,
) -> None:
    """An active (not yet settled) market: market row inserts, settlement row doesn't."""
    _seed_identity(db_session)
    _add_alias(db_session, "Victor Wembanyama", 1641705)

    rows = {
        "KXNBAPTS": [
            _synthetic_market_row(
                ticker="KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35",
                settlement_ts=None,  # not settled
            )
        ],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    summary = load_settled_markets(cache, db_session)
    assert summary.markets_inserted == 1
    assert summary.settlements_inserted == 0
    assert summary.settlements_unsettled == 1

    assert db_session.get(MarketSettlement, "KXNBAPTS-26MAY30SASOKC-SASVWEMBANYAMA1-35") is None
