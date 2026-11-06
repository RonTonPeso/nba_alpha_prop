"""Point-in-time yes mid for one Kalshi market.

ADR-3 leaves the choice of mid versus last trade open and says the
historical backfill does not contain the book from before polling
started. The mid is the choice. A missing side is not filled in from
``last_price``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc
from sqlmodel import Session, select

from app.db.tables import MarketSnapshot


def yes_mid(yes_bid: float | None, yes_ask: float | None) -> float | None:
    """(yes_bid + yes_ask) / 2 when the book is two-sided and inside [0, 1]."""
    if yes_bid is None or yes_ask is None:
        return None
    if yes_ask < yes_bid:
        return None
    mid = (yes_bid + yes_ask) / 2.0
    if mid < 0.0 or mid > 1.0:
        return None
    return mid


def latest_yes_mid(session: Session, ticker: str, as_of: datetime) -> float | None:
    """Latest visible mid at ``as_of``.

    Visible means ``quoted_at <= as_of`` and ``ingested_at <= as_of``.
    A quote that was true earlier but loaded later stays hidden.
    """
    row = session.exec(
        select(MarketSnapshot)
        .where(
            MarketSnapshot.ticker == ticker,
            MarketSnapshot.quoted_at <= as_of,
            MarketSnapshot.ingested_at <= as_of,
        )
        .order_by(desc(MarketSnapshot.quoted_at))  # type: ignore[arg-type]
    ).first()
    if row is None:
        return None
    return yes_mid(row.yes_bid, row.yes_ask)
