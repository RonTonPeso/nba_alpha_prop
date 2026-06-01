"""Bulk historical loader for Kalshi NBA prop markets.

Pulls markets for the three covered series (points, rebounds, assists),
resolves player + game aliases against M1's identity tables, upserts
into `markets`, and inserts `market_settlements` for finalized markets.

Idempotent: re-running pulls the same paginated cache rows (zero
network) and skips already-inserted markets/settlements by PK. If the
alias table has grown since last run, previously-NULL FKs on existing
markets get backfilled.

Snapshots are NOT written by this loader. Live snapshots come from the
APScheduler 5-min job in `app/data/kalshi_snapshot.py`.

Run:
    uv run python -m app.data.kalshi_bulk_load \\
        --min-close-date 2025-11-01 \\
        --max-close-date 2026-05-31
"""

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlmodel import Session, select

from app.data.cache import CachedHttpClient
from app.data.kalshi import (
    _SERIES_TO_PROP,
    iter_markets,
    market_row_to_orm,
    market_row_to_settlement,
)
from app.db.engine import get_engine
from app.db.tables import (
    Game,
    KalshiPlayerAlias,
    Market,
    MarketSettlement,
    Team,
)

logger = logging.getLogger(__name__)


# Kalshi added NBA prop coverage in November 2025. Earlier windows return
# nothing useful and burn pagination calls.
_DEFAULT_MIN_CLOSE_DATE = date(2025, 11, 1)


@dataclass
class BulkLoadSummary:
    """Per-run counters. Surface as a one-line log message at the end."""

    series: list[str] = field(default_factory=list)
    markets_seen: int = 0
    markets_inserted: int = 0
    markets_skipped: int = 0  # already existed
    markets_errors: int = 0  # parser failure (bad ticker / rules / etc.)

    settlements_inserted: int = 0
    settlements_skipped: int = 0
    settlements_unsettled: int = 0  # market not yet settled, no row written

    players_resolved: int = 0  # FK populated at insert OR backfilled on rerun
    players_unmapped: int = 0  # name not in alias table
    games_resolved: int = 0
    games_unmapped: int = 0  # date+abbrs didn't match any M1 game

    elapsed_seconds: float = 0.0
    unmapped_player_names: set[str] = field(default_factory=set)


def build_team_abbr_map(session: Session) -> dict[str, int]:
    teams = session.exec(select(Team)).all()
    return {t.abbreviation: t.team_id for t in teams}


def build_player_alias_map(session: Session) -> dict[str, int]:
    aliases = session.exec(select(KalshiPlayerAlias)).all()
    return {a.kalshi_player_name: a.player_id for a in aliases}


def build_game_map(session: Session) -> dict[tuple[date, int, int], str]:
    """(game_date, away_team_id, home_team_id) -> game_id.

    Built once at loader start. ~5000 rows for a full season; small.
    """
    games = session.exec(select(Game)).all()
    return {(g.game_date, g.away_team_id, g.home_team_id): g.game_id for g in games}


def _existing_market_tickers(session: Session) -> set[str]:
    return set(session.exec(select(Market.ticker)).all())


def _existing_settlement_tickers(session: Session) -> set[str]:
    return set(session.exec(select(MarketSettlement.ticker)).all())


def resolve_game_id(
    market: Market,
    *,
    team_abbr_map: dict[str, int],
    game_map: dict[tuple[date, int, int], str],
) -> str | None:
    away_team_id = team_abbr_map.get(market.kalshi_away_abbr)
    home_team_id = team_abbr_map.get(market.kalshi_home_abbr)
    if away_team_id is None or home_team_id is None:
        return None
    return game_map.get((market.kalshi_event_date, away_team_id, home_team_id))


def load_settled_markets(
    client: CachedHttpClient,
    session: Session,
    *,
    series_tickers: list[str] | None = None,
    min_close_ts: int | None = None,
    max_close_ts: int | None = None,
    page_size: int = 200,
) -> BulkLoadSummary:
    """Pull, parse, resolve, upsert. Caller commits.

    `min_close_ts` / `max_close_ts` are unix-seconds bounds on
    `close_time`, passed through to the Kalshi API. None = unbounded.
    """
    series_tickers = series_tickers or list(_SERIES_TO_PROP.keys())
    summary = BulkLoadSummary(series=list(series_tickers))
    start = time.monotonic()

    logger.info("Loading Kalshi markets for series: %s", ", ".join(series_tickers))

    team_abbr_map = build_team_abbr_map(session)
    player_alias_map = build_player_alias_map(session)
    game_map = build_game_map(session)
    logger.info(
        "Resolution maps: %d teams, %d player aliases, %d games",
        len(team_abbr_map),
        len(player_alias_map),
        len(game_map),
    )

    existing_markets = _existing_market_tickers(session)
    existing_settlements = _existing_settlement_tickers(session)

    pending_settlements: list[MarketSettlement] = []

    for series_ticker in series_tickers:
        for row in iter_markets(
            client,
            series_ticker=series_ticker,
            page_size=page_size,
            min_close_ts=min_close_ts,
            max_close_ts=max_close_ts,
        ):
            summary.markets_seen += 1
            try:
                market = market_row_to_orm(row)
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Skipping malformed market %s: %s", row.get("ticker"), exc)
                summary.markets_errors += 1
                continue

            resolved_player_id = player_alias_map.get(market.kalshi_player_name)
            resolved_game_id = resolve_game_id(
                market, team_abbr_map=team_abbr_map, game_map=game_map
            )
            market.player_id = resolved_player_id
            market.game_id = resolved_game_id

            if market.ticker in existing_markets:
                # Backfill NULL FKs if the alias table has grown.
                existing = session.get(Market, market.ticker)
                assert existing is not None  # PK in existing_markets, must be in DB
                if existing.player_id is None and resolved_player_id is not None:
                    existing.player_id = resolved_player_id
                    summary.players_resolved += 1
                if existing.game_id is None and resolved_game_id is not None:
                    existing.game_id = resolved_game_id
                    summary.games_resolved += 1
                summary.markets_skipped += 1
            else:
                session.add(market)
                existing_markets.add(market.ticker)
                summary.markets_inserted += 1
                if resolved_player_id is not None:
                    summary.players_resolved += 1
                if resolved_game_id is not None:
                    summary.games_resolved += 1

            if resolved_player_id is None:
                summary.players_unmapped += 1
                summary.unmapped_player_names.add(market.kalshi_player_name)
            if resolved_game_id is None:
                summary.games_unmapped += 1

            # Queue settlement, if any. Markets need to flush first so FK resolves.
            settlement = market_row_to_settlement(row)
            if settlement is None:
                summary.settlements_unsettled += 1
                continue
            if settlement.ticker in existing_settlements:
                summary.settlements_skipped += 1
                continue
            pending_settlements.append(settlement)
            existing_settlements.add(settlement.ticker)

    # Markets first so MarketSettlement.ticker FK resolves.
    session.flush()

    for settlement in pending_settlements:
        session.add(settlement)
        summary.settlements_inserted += 1
    session.flush()

    summary.elapsed_seconds = time.monotonic() - start
    logger.info("\n%s", _format_summary(summary))
    return summary


def _format_summary(s: BulkLoadSummary) -> str:
    lines = [
        f"Kalshi bulk load: series={','.join(s.series)}",
        f"  markets: seen {s.markets_seen}  +{s.markets_inserted} new"
        f"  ({s.markets_skipped} skipped, {s.markets_errors} errors)",
        f"  settlements: +{s.settlements_inserted} new"
        f"  ({s.settlements_skipped} skipped, {s.settlements_unsettled} unsettled)",
        f"  player FKs: {s.players_resolved} resolved,"
        f"  {s.players_unmapped} unmapped"
        f"  ({len(s.unmapped_player_names)} unique names)",
        f"  game FKs: {s.games_resolved} resolved, {s.games_unmapped} unmapped",
        f"  done in {s.elapsed_seconds:.1f}s",
    ]
    if s.unmapped_player_names and len(s.unmapped_player_names) <= 25:
        names = sorted(s.unmapped_player_names)
        lines.append(f"  unmapped names: {', '.join(names)}")
    return "\n".join(lines)


def _date_to_unix(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def _parse_date_arg(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kalshi_bulk_load",
        description="Bulk-load Kalshi NBA prop markets into Postgres.",
    )
    parser.add_argument(
        "--series",
        nargs="*",
        default=list(_SERIES_TO_PROP.keys()),
        help="Series tickers to load. Default: KXNBAPTS KXNBAREB KXNBAAST",
    )
    parser.add_argument(
        "--min-close-date",
        type=_parse_date_arg,
        default=_DEFAULT_MIN_CLOSE_DATE,
        help="Lower bound on close_time. Default: 2025-11-01 (Kalshi NBA coverage start)",
    )
    parser.add_argument(
        "--max-close-date",
        type=_parse_date_arg,
        default=None,
        help="Upper bound on close_time. Default: unbounded (catches active markets too)",
    )
    parser.add_argument("--page-size", type=int, default=200)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    min_close_ts = _date_to_unix(args.min_close_date) if args.min_close_date else None
    max_close_ts = (
        _date_to_unix(args.max_close_date + timedelta(days=1)) if args.max_close_date else None
    )

    engine = get_engine()
    with Session(engine) as session, CachedHttpClient(session) as client:
        try:
            load_settled_markets(
                client,
                session,
                series_tickers=list(args.series),
                min_close_ts=min_close_ts,
                max_close_ts=max_close_ts,
                page_size=args.page_size,
            )
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Bulk load failed; rolled back")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
