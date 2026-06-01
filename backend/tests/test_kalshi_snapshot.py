"""Tests for the Kalshi snapshot job.

Covers: round-trip happy path (markets + snapshots inserted with
resolved FKs), opportunistic settlement writing, idempotency
(composite PK dedup on snapshots), never-seen market insertion,
defensive close_time skip, unmapped-alias fallthrough.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlmodel import Session, select

from app.data.cache import CachedHttpClient
from app.data.kalshi_snapshot import snapshot_active_markets
from app.db.tables import (
    Game,
    KalshiPlayerAlias,
    Market,
    MarketSettlement,
    MarketSnapshot,
    Player,
    RequestCache,
    Team,
)
from tests._fakes import FakeResponse, FakeSession

# ---------- seeding helpers (mirror test_kalshi_bulk_load.py) ----------


def _seed_identity(session: Session) -> None:
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


def _add_alias(session: Session, name: str, player_id: int) -> None:
    session.add(KalshiPlayerAlias(kalshi_player_name=name, player_id=player_id))
    session.flush()


def _active_market_row(
    *,
    ticker: str,
    player_name: str = "Victor Wembanyama",
    line: float = 34.5,
    close_time: str = "2027-01-01T03:10:00Z",  # far future so close_time > now
    updated_time: str = "2026-05-31T03:00:00Z",
    settled: bool = False,
    series_ticker: str = "KXNBAPTS",
    event_date_str: str = "26MAY30",
    away_abbr: str = "SAS",
    home_abbr: str = "OKC",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ticker": ticker,
        "event_ticker": f"{series_ticker}-{event_date_str}{away_abbr}{home_abbr}",
        "title": f"{player_name}: line {line}",
        "rules_primary": (
            f"If {player_name} records {int(line) + 1}+ Points in the X "
            f"vs Y professional basketball game originally scheduled for "
            f"May 30, 2026, then the market resolves to Yes."
        ),
        "floor_strike": line,
        "strike_type": "structured",
        "open_time": "2026-05-29T04:10:00Z",
        "close_time": close_time,
        "status": "active" if not settled else "finalized",
        "updated_time": updated_time,
        "yes_bid_dollars": "0.20",
        "yes_ask_dollars": "0.25",
        "no_bid_dollars": "0.75",
        "no_ask_dollars": "0.80",
        "last_price_dollars": "0.22",
        "volume_fp": "100.00",
        "volume_24h_fp": "30.00",
        "open_interest_fp": "150.00",
        "liquidity_dollars": "5.5",
    }
    if settled:
        row["settlement_ts"] = "2026-05-31T03:16:20.645898Z"
        row["settlement_value_dollars"] = "1.00"
        row["result"] = "yes"
    return row


def _make_handler(rows_by_series: dict[str, list[dict[str, Any]]]) -> Any:
    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        series = params.get("series_ticker", "")
        rows = rows_by_series.get(series, [])
        return FakeResponse(200, {"markets": rows, "cursor": ""})

    return handler


_NOW = datetime(2026, 5, 31, 2, 0, tzinfo=UTC)


# ---------- round trip ----------


def test_snapshot_round_trip_inserts_market_and_snapshot(db_session: Session) -> None:
    _seed_identity(db_session)
    _add_alias(db_session, "Victor Wembanyama", 1641705)

    rows = {
        "KXNBAPTS": [_active_market_row(ticker="KXNBAPTS-26MAY30SASOKC-A-35")],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    summary = snapshot_active_markets(cache, db_session, now=_NOW)

    assert summary.markets_seen == 1
    assert summary.markets_inserted_new == 1
    assert summary.snapshots_inserted == 1
    assert summary.players_resolved == 1
    assert summary.games_resolved == 1

    market = db_session.get(Market, "KXNBAPTS-26MAY30SASOKC-A-35")
    assert market is not None
    assert market.player_id == 1641705
    assert market.game_id == "0022500999"

    snapshots = list(db_session.exec(select(MarketSnapshot)).all())
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.ticker == "KXNBAPTS-26MAY30SASOKC-A-35"
    assert snap.quoted_at == datetime(2026, 5, 31, 3, 0, tzinfo=UTC)
    assert snap.yes_bid == 0.20
    assert snap.yes_ask == 0.25


# ---------- opportunistic settlement ----------


def test_snapshot_writes_settlement_for_finalized_market(db_session: Session) -> None:
    """If a polled market has result + settlement_ts, write the settlement too."""
    _seed_identity(db_session)
    _add_alias(db_session, "Victor Wembanyama", 1641705)

    rows = {
        "KXNBAPTS": [
            _active_market_row(
                ticker="KXNBAPTS-26MAY30SASOKC-B-30",
                settled=True,
            )
        ],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    summary = snapshot_active_markets(cache, db_session, now=_NOW)

    assert summary.settlements_inserted == 1
    settlement = db_session.get(MarketSettlement, "KXNBAPTS-26MAY30SASOKC-B-30")
    assert settlement is not None
    assert settlement.result == "yes"
    assert settlement.settlement_value == 1.0


# ---------- idempotency ----------


def test_snapshot_dedups_on_composite_pk_on_rerun(db_session: Session) -> None:
    """Second snapshot tick against same handler writes zero new snapshots."""
    _seed_identity(db_session)
    _add_alias(db_session, "Victor Wembanyama", 1641705)

    rows = {
        "KXNBAPTS": [_active_market_row(ticker="KXNBAPTS-26MAY30SASOKC-C-25")],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    first = snapshot_active_markets(cache, db_session, now=_NOW)
    assert first.snapshots_inserted == 1

    # Second tick: same updated_time => same quoted_at => composite PK dup.
    second = snapshot_active_markets(cache, db_session, now=_NOW + timedelta(minutes=5))
    assert second.snapshots_inserted == 0
    assert second.snapshots_duplicate == 1
    assert second.markets_inserted_new == 0
    assert second.markets_existing == 1

    snapshots = list(db_session.exec(select(MarketSnapshot)).all())
    assert len(snapshots) == 1


def test_snapshot_inserts_second_row_when_kalshi_updated_time_advances(
    db_session: Session,
) -> None:
    """A new updated_time => new quoted_at => new composite PK => new row."""
    _seed_identity(db_session)
    _add_alias(db_session, "Victor Wembanyama", 1641705)

    rows_tick_1 = {
        "KXNBAPTS": [
            _active_market_row(
                ticker="KXNBAPTS-26MAY30SASOKC-D-40",
                updated_time="2026-05-31T03:00:00Z",
            )
        ],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake1 = FakeSession(_make_handler(rows_tick_1))
    cache1 = CachedHttpClient(db_session, client=fake1)
    snapshot_active_markets(cache1, db_session, now=_NOW)

    # Simulate the request_cache TTL expiring between ticks (production: 4 min).
    db_session.exec(delete(RequestCache))
    db_session.flush()

    rows_tick_2 = {
        "KXNBAPTS": [
            _active_market_row(
                ticker="KXNBAPTS-26MAY30SASOKC-D-40",
                updated_time="2026-05-31T03:05:00Z",  # advanced
            )
        ],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake2 = FakeSession(_make_handler(rows_tick_2))
    cache2 = CachedHttpClient(db_session, client=fake2)
    summary = snapshot_active_markets(cache2, db_session, now=_NOW + timedelta(minutes=5))

    assert summary.snapshots_inserted == 1
    assert len(list(db_session.exec(select(MarketSnapshot)).all())) == 2


# ---------- defensive close_time skip ----------


def test_snapshot_skips_markets_whose_close_time_has_passed(db_session: Session) -> None:
    """Even if Kalshi flags a market as `active`, skip if close_time <= now."""
    _seed_identity(db_session)
    _add_alias(db_session, "Victor Wembanyama", 1641705)

    rows = {
        "KXNBAPTS": [
            _active_market_row(
                ticker="KXNBAPTS-26MAY30SASOKC-E-35",
                close_time="2026-05-30T00:00:00Z",  # before _NOW
            )
        ],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    summary = snapshot_active_markets(cache, db_session, now=_NOW)

    assert summary.markets_seen == 1
    assert summary.markets_skipped_closed == 1
    assert summary.markets_inserted_new == 0
    assert summary.snapshots_inserted == 0


# ---------- unmapped alias fallthrough ----------


def test_snapshot_inserts_snapshot_with_null_player_id_when_alias_missing(
    db_session: Session,
) -> None:
    """Snapshot row still written even when player alias is absent."""
    _seed_identity(db_session)
    # No alias added.

    rows = {
        "KXNBAPTS": [_active_market_row(ticker="KXNBAPTS-26MAY30SASOKC-F-35")],
        "KXNBAREB": [],
        "KXNBAAST": [],
    }
    fake = FakeSession(_make_handler(rows))
    cache = CachedHttpClient(db_session, client=fake)

    summary = snapshot_active_markets(cache, db_session, now=_NOW)

    assert summary.snapshots_inserted == 1
    assert summary.players_unmapped == 1
    assert "Victor Wembanyama" in summary.unmapped_player_names

    market = db_session.get(Market, "KXNBAPTS-26MAY30SASOKC-F-35")
    assert market is not None
    assert market.player_id is None
    assert market.game_id == "0022500999"
