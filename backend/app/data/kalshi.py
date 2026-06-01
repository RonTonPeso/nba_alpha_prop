"""Kalshi NBA prop market client: fetch + parse.

All HTTP routes through ``CachedHttpClient``. Public REST API only; no
auth, no trading endpoints.

Series we care about for v1:
- ``KXNBAPTS`` -> points
- ``KXNBAREB`` -> rebounds
- ``KXNBAAST`` -> assists

Other series exist (KXNBA3PT, KXNBAPRA, etc.) but are out of scope per
PRD section 9. The parser raises on unrecognized series so a future
expansion is a deliberate change.

Each Kalshi market is binary Yes/No at one strike. Wembanyama 25+/30+/35+
points are three distinct tickers sharing one ``event_ticker``.

See docs/adr.md ADR-3 for schema rationale.
"""

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.data.cache import CachedHttpClient
from app.db.tables import Market, MarketSettlement, MarketSnapshot

_KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"

_SERIES_TO_PROP: dict[str, str] = {
    "KXNBAPTS": "points",
    "KXNBAREB": "rebounds",
    "KXNBAAST": "assists",
}

_MONTH_ABBR: dict[str, int] = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}  # fmt: skip

_PLAYER_RULES_RE = re.compile(r"^If (.+?) records ")


def _parse_kalshi_date(s: str) -> date:
    """``'26MAY30'`` -> ``date(2026, 5, 30)``.

    Format: YY (2 digits) + MMM (3 uppercase letters) + DD (2 digits).
    Years 00-79 -> 2000-2079; 80-99 -> 1980-1999. NBA props didn't exist
    before 2025 but the rule keeps us safe past 2079.
    """
    if len(s) != 7:
        raise ValueError(f"Kalshi date {s!r} is not 7 chars")
    mmm = s[2:5]
    if mmm not in _MONTH_ABBR:
        raise ValueError(f"Unknown month abbr {mmm!r} in {s!r}")
    yy = int(s[0:2])
    dd = int(s[5:7])
    year = 2000 + yy if yy < 80 else 1900 + yy
    return date(year, _MONTH_ABBR[mmm], dd)


def _parse_event_ticker(event_ticker: str) -> tuple[str, date, str, str]:
    """``'KXNBAPTS-26MAY30SASOKC'`` -> ``('KXNBAPTS', date(2026,5,30), 'SAS', 'OKC')``.

    Returns ``(series_ticker, event_date, away_abbr, home_abbr)``.

    NBA team abbreviations are always 3 chars on Kalshi (LAL, BOS, OKC,
    SAS, etc.). The tail after the date is therefore exactly 6 chars:
    ``away (3) + home (3)``.
    """
    parts = event_ticker.split("-")
    if len(parts) != 2:
        raise ValueError(f"event_ticker {event_ticker!r} not in SERIES-DATEGAMES form")
    series_ticker, tail = parts
    if len(tail) != 13:
        raise ValueError(f"event_ticker tail {tail!r} expected 13 chars (7 date + 6 abbrs)")
    event_date = _parse_kalshi_date(tail[:7])
    away = tail[7:10]
    home = tail[10:13]
    return series_ticker, event_date, away, home


def _parse_player_from_rules(rules_primary: str) -> str:
    """Extract canonical English player name from ``rules_primary``.

    Example: ``'If Victor Wembanyama records 35+ Points in the San
    Antonio vs Oklahoma City professional basketball game...'``
    -> ``'Victor Wembanyama'``.

    More reliable than the ticker's player code, which is uppercase and
    sometimes has a trailing disambiguation digit.
    """
    m = _PLAYER_RULES_RE.match(rules_primary)
    if not m:
        raise ValueError(f"rules_primary doesn't match expected pattern: {rules_primary[:80]!r}")
    return m.group(1).strip()


def _parse_iso_utc(s: str) -> datetime:
    """Kalshi ISO-8601 datetime -> aware UTC datetime."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _to_float_or_none(v: Any) -> float | None:
    """Coerce Kalshi's stringified numerics to float, tolerant of missing."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_markets_page(
    client: CachedHttpClient,
    *,
    series_ticker: str,
    status: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
    min_close_ts: int | None = None,
    max_close_ts: int | None = None,
    ttl: timedelta | None = None,
) -> dict[str, Any]:
    """Fetch one page of Kalshi markets. Returns the full JSON body.

    ``status``: ``'open'``, ``'closed'``, ``'settled'``. None = all.
    ``min_close_ts`` / ``max_close_ts`` are unix seconds bounds on
    ``close_time``; useful for backfilling specific windows.
    """
    params: dict[str, Any] = {"series_ticker": series_ticker, "limit": limit}
    if status is not None:
        params["status"] = status
    if cursor is not None:
        params["cursor"] = cursor
    if min_close_ts is not None:
        params["min_close_ts"] = min_close_ts
    if max_close_ts is not None:
        params["max_close_ts"] = max_close_ts
    body = client.get(f"{_KALSHI_BASE}/markets", params=params, ttl=ttl)
    if not isinstance(body, dict):
        raise ValueError(f"Expected dict response from Kalshi /markets, got {type(body)}")
    return body


def iter_markets(
    client: CachedHttpClient,
    *,
    series_ticker: str,
    status: str | None = None,
    page_size: int = 200,
    min_close_ts: int | None = None,
    max_close_ts: int | None = None,
    ttl: timedelta | None = None,
    max_pages: int = 1000,
) -> Iterator[dict[str, Any]]:
    """Page through all markets matching filter, yielding one row at a time.

    Stops when the API returns no cursor or an empty page. ``max_pages``
    is a safety belt against a runaway cursor loop.
    """
    cursor: str | None = None
    for _ in range(max_pages):
        body = fetch_markets_page(
            client,
            series_ticker=series_ticker,
            status=status,
            limit=page_size,
            cursor=cursor,
            min_close_ts=min_close_ts,
            max_close_ts=max_close_ts,
            ttl=ttl,
        )
        markets = body.get("markets") or []
        yield from markets
        cursor = body.get("cursor")
        if not cursor or not markets:
            return


def market_row_to_orm(row: dict[str, Any]) -> Market:
    """Kalshi market dict -> ``Market`` ORM object (with NULL FKs).

    FKs (``player_id``, ``game_id``) are not resolved here; the caller
    runs alias resolution against ``kalshi_player_aliases`` and the
    ``games`` table separately.
    """
    event_ticker = str(row["event_ticker"])
    series_ticker, event_date, away_abbr, home_abbr = _parse_event_ticker(event_ticker)
    prop_type = _SERIES_TO_PROP.get(series_ticker)
    if prop_type is None:
        raise ValueError(
            f"Unrecognized series_ticker {series_ticker!r} "
            f"(v1 supports only points/rebounds/assists)"
        )
    player_name = _parse_player_from_rules(str(row["rules_primary"]))

    return Market(
        ticker=str(row["ticker"]),
        series_ticker=series_ticker,
        event_ticker=event_ticker,
        prop_type=prop_type,
        line=float(row["floor_strike"]),
        strike_type=str(row.get("strike_type", "structured")),
        open_time=_parse_iso_utc(str(row["open_time"])),
        close_time=_parse_iso_utc(str(row["close_time"])),
        title=str(row.get("title", "")),
        rules_primary=str(row["rules_primary"]),
        kalshi_player_name=player_name,
        kalshi_event_date=event_date,
        kalshi_away_abbr=away_abbr,
        kalshi_home_abbr=home_abbr,
        raw_data=row,
    )


def market_row_to_snapshot(
    row: dict[str, Any],
    *,
    quoted_at: datetime | None = None,
) -> MarketSnapshot:
    """Kalshi market dict -> ``MarketSnapshot`` ORM object.

    ``quoted_at`` defaults to the response's ``updated_time``; falls back
    to "now" only if Kalshi didn't send one. Honest timing matters here
    because cached responses can be a few minutes stale.
    """
    if quoted_at is None:
        updated_time = row.get("updated_time")
        if isinstance(updated_time, str) and updated_time:
            quoted_at = _parse_iso_utc(updated_time)
        else:
            quoted_at = datetime.now(UTC)

    return MarketSnapshot(
        ticker=str(row["ticker"]),
        quoted_at=quoted_at,
        yes_bid=_to_float_or_none(row.get("yes_bid_dollars")),
        yes_ask=_to_float_or_none(row.get("yes_ask_dollars")),
        no_bid=_to_float_or_none(row.get("no_bid_dollars")),
        no_ask=_to_float_or_none(row.get("no_ask_dollars")),
        last_price=_to_float_or_none(row.get("last_price_dollars")),
        volume=_to_float_or_none(row.get("volume_fp")),
        volume_24h=_to_float_or_none(row.get("volume_24h_fp")),
        open_interest=_to_float_or_none(row.get("open_interest_fp")),
        liquidity=_to_float_or_none(row.get("liquidity_dollars")),
        status=str(row.get("status", "")),
        raw_data=row,
    )


def market_row_to_settlement(row: dict[str, Any]) -> MarketSettlement | None:
    """Kalshi market dict -> ``MarketSettlement``, or None if not settled.

    Settled markets carry ``settlement_ts`` and ``result`` in
    ``{'yes', 'no'}``. Anything else returns None.
    """
    settlement_ts = row.get("settlement_ts")
    result = row.get("result")
    if not settlement_ts or result not in ("yes", "no"):
        return None

    settlement_value = _to_float_or_none(row.get("settlement_value_dollars"))
    return MarketSettlement(
        ticker=str(row["ticker"]),
        result=str(result),
        settlement_value=settlement_value if settlement_value is not None else 0.0,
        settled_at=_parse_iso_utc(str(settlement_ts)),
        raw_data=row,
    )
