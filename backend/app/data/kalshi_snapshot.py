"""Live 5-min snapshot job for Kalshi NBA prop markets.

For each currently-active market, upserts the Market row (with alias
resolution via M1's identity tables) and inserts a MarketSnapshot.
Opportunistically writes MarketSettlement for markets that finalized
since the last tick, so we don't need to re-run kalshi_bulk_load to
catch fresh settlements.

Idempotent: composite PK (ticker, quoted_at) on market_snapshots dedups
within-tick re-fires; PK on market_settlements blocks duplicate rows.
The Kalshi response carries `updated_time`, which becomes `quoted_at` on
the snapshot, so cache-served responses still write the right timestamp
and dedup correctly if Kalshi hasn't pushed an update.

Scheduled by app/scheduler.py at IntervalTrigger(minutes=5). Gated by
SCHEDULER_ENABLED env var.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.data.cache import CachedHttpClient
from app.data.kalshi import (
    _SERIES_TO_PROP,
    iter_markets,
    market_row_to_orm,
    market_row_to_settlement,
    market_row_to_snapshot,
)
from app.data.kalshi_bulk_load import (
    build_game_map,
    build_player_alias_map,
    build_team_abbr_map,
    resolve_game_id,
)
from app.db.engine import get_engine
from app.db.tables import Market, MarketSettlement, MarketSnapshot

logger = logging.getLogger(__name__)


# Just under the 5-min scheduler cadence so within-tick re-fires hit cache
# but the next tick fetches fresh.
_SNAPSHOT_CACHE_TTL = timedelta(minutes=4)


@dataclass
class SnapshotSummary:
    """Per-tick counters. Logged at the end of each run."""

    series: list[str] = field(default_factory=list)

    markets_seen: int = 0
    markets_inserted_new: int = 0
    markets_existing: int = 0
    markets_skipped_closed: int = 0  # close_time <= now (defensive)
    markets_errors: int = 0  # parser failure

    snapshots_inserted: int = 0
    snapshots_duplicate: int = 0  # composite PK already existed

    settlements_inserted: int = 0
    settlements_existing: int = 0

    players_resolved: int = 0
    players_unmapped: int = 0
    games_resolved: int = 0
    games_unmapped: int = 0
    unmapped_player_names: set[str] = field(default_factory=set)

    elapsed_seconds: float = 0.0


def snapshot_active_markets(
    client: CachedHttpClient,
    session: Session,
    *,
    now: datetime,
    series_tickers: list[str] | None = None,
    page_size: int = 200,
) -> SnapshotSummary:
    """Pull active markets, upsert, snapshot, opportunistically settle. Caller commits.

    `now` is parameterizable for deterministic tests; production passes
    `datetime.now(UTC)`.

    FK ordering: new Markets must flush before MarketSnapshots and
    MarketSettlements reference them. Implemented as two passes (queue,
    then flush+add) so we don't depend on SQLAlchemy's unit-of-work
    topology sort (which doesn't always feed off SQLModel's `foreign_key=`
    declarations reliably; same lesson as M1).
    """
    series_tickers = series_tickers or list(_SERIES_TO_PROP.keys())
    summary = SnapshotSummary(series=list(series_tickers))
    start = time.monotonic()

    team_abbr_map = build_team_abbr_map(session)
    player_alias_map = build_player_alias_map(session)
    game_map = build_game_map(session)

    new_markets: list[Market] = []
    queued_snapshots: list[MarketSnapshot] = []
    queued_settlements: list[MarketSettlement] = []

    for series_ticker in series_tickers:
        for row in iter_markets(
            client,
            series_ticker=series_ticker,
            status="active",
            page_size=page_size,
            ttl=_SNAPSHOT_CACHE_TTL,
        ):
            summary.markets_seen += 1
            try:
                market = market_row_to_orm(row)
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Skipping malformed market %s: %s", row.get("ticker"), exc)
                summary.markets_errors += 1
                continue

            # Defensive: if API still calls this "active" but close_time has
            # passed, skip — we don't want a stale snapshot.
            if market.close_time <= now:
                summary.markets_skipped_closed += 1
                continue

            resolved_player_id = player_alias_map.get(market.kalshi_player_name)
            resolved_game_id = resolve_game_id(
                market, team_abbr_map=team_abbr_map, game_map=game_map
            )

            existing_market = session.get(Market, market.ticker)
            if existing_market is None:
                market.player_id = resolved_player_id
                market.game_id = resolved_game_id
                new_markets.append(market)
                summary.markets_inserted_new += 1
                if resolved_player_id is not None:
                    summary.players_resolved += 1
                if resolved_game_id is not None:
                    summary.games_resolved += 1
            else:
                # Backfill NULL FKs if alias table has grown.
                if existing_market.player_id is None and resolved_player_id is not None:
                    existing_market.player_id = resolved_player_id
                    summary.players_resolved += 1
                if existing_market.game_id is None and resolved_game_id is not None:
                    existing_market.game_id = resolved_game_id
                    summary.games_resolved += 1
                summary.markets_existing += 1

            if resolved_player_id is None:
                summary.players_unmapped += 1
                summary.unmapped_player_names.add(market.kalshi_player_name)
            if resolved_game_id is None:
                summary.games_unmapped += 1

            # Build snapshot. Composite PK check happens after flush.
            snapshot = market_row_to_snapshot(row)
            queued_snapshots.append(snapshot)

            # Settlement if finalized.
            settlement = market_row_to_settlement(row)
            if settlement is not None:
                queued_settlements.append(settlement)

    # Flush markets so FKs on snapshots / settlements resolve.
    for m in new_markets:
        session.add(m)
    session.flush()

    # Snapshots: dedup against composite PK, then insert.
    for snapshot in queued_snapshots:
        existing_snap = session.get(MarketSnapshot, (snapshot.ticker, snapshot.quoted_at))
        if existing_snap is not None:
            summary.snapshots_duplicate += 1
            continue
        session.add(snapshot)
        summary.snapshots_inserted += 1
    session.flush()

    # Settlements: PK dedup.
    for settlement in queued_settlements:
        existing_settle = session.get(MarketSettlement, settlement.ticker)
        if existing_settle is not None:
            summary.settlements_existing += 1
            continue
        session.add(settlement)
        summary.settlements_inserted += 1
    session.flush()

    summary.elapsed_seconds = time.monotonic() - start
    logger.info("\n%s", _format_summary(summary))
    return summary


def _format_summary(s: SnapshotSummary) -> str:
    return (
        f"Kalshi snapshot tick: series={','.join(s.series)}\n"
        f"  markets: seen {s.markets_seen}  +{s.markets_inserted_new} new"
        f"  {s.markets_existing} existing"
        f"  ({s.markets_skipped_closed} closed-skip,"
        f" {s.markets_errors} errors)\n"
        f"  snapshots: +{s.snapshots_inserted}  ({s.snapshots_duplicate} duplicate)\n"
        f"  settlements: +{s.settlements_inserted}  ({s.settlements_existing} existing)\n"
        f"  FKs: {s.players_resolved} players resolved,"
        f" {s.players_unmapped} unmapped"
        f" ({len(s.unmapped_player_names)} unique names)\n"
        f"  done in {s.elapsed_seconds:.1f}s"
    )


def run_snapshot() -> SnapshotSummary:
    """Entrypoint for APScheduler. Opens its own session + cache and commits."""
    now = datetime.now(UTC)
    logger.info("Kalshi snapshot tick at %s", now.isoformat())
    engine = get_engine()
    with Session(engine) as session, CachedHttpClient(session) as client:
        try:
            summary = snapshot_active_markets(client, session, now=now)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Snapshot tick failed; rolled back")
            raise
    return summary
