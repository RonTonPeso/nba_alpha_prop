"""nba_api endpoint wrappers and row parsers.

We don't depend on the ``nba_api`` library. Its value is its Endpoint
classes that fetch and parse, and we need the fetch to go through
``CachedHttpClient`` instead. So we hardcode the URL and the magic
browser headers that ``stats.nba.com`` requires (without them it
returns 403).

One endpoint covers M1's needs: ``LeagueGameLog``. Two calls per season:
- ``PlayerOrTeam='P'`` → one row per (player, game). Source for
  ``player_game_logs`` and ``players``.
- ``PlayerOrTeam='T'`` → one row per (team, game). Source for ``games``,
  ``game_results``, and ``teams``.

Daily incremental uses the same fetcher with ``DateFrom``/``DateTo`` set.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from app.data.cache import CachedHttpClient
from app.db.tables import Game, GameResult, Player, PlayerGameLog, Team

_NBA_STATS_BASE = "https://stats.nba.com/stats"

# stats.nba.com returns 403 without browser-like headers. These mirror
# what nba_api sends. Stable for years; if 403s start showing up, this
# constant is the first place to check.
_NBA_HEADERS: dict[str, str] = {
    "Host": "stats.nba.com",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://stats.nba.com/",
    "Origin": "https://stats.nba.com",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}


def _parse_result_set(body: dict[str, Any], index: int = 0) -> list[dict[str, Any]]:
    """Zip ``resultSets[index]`` headers with each rowSet entry into dicts."""
    rs = body["resultSets"][index]
    headers = rs["headers"]
    return [dict(zip(headers, row, strict=True)) for row in rs["rowSet"]]


def _parse_minutes(raw: Any) -> float | None:
    """Handle the ``MIN`` field: 'MM:SS' string, float, int, None, or empty."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, int | float):
        return float(raw)
    s = str(raw).strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 2:
            return None
        try:
            mins, secs = int(parts[0]), int(parts[1])
        except ValueError:
            return None
        return mins + secs / 60.0
    try:
        return float(s)
    except ValueError:
        return None


def _event_time_from_game_date(game_date: str) -> datetime:
    """``YYYY-MM-DD`` → next-day midnight UTC.

    Conservative approximation. LeagueGameLog doesn't include tip times.
    The real point-in-time enforcer is ``ingested_at``; event_time being
    slightly late just means the game ordering is one notch off, never
    a leak. We never insert a row for a game we haven't seen the box
    score for, so ingested_at is always honest.
    """
    d = date.fromisoformat(game_date)
    return datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=1)


def fetch_league_game_log(
    client: CachedHttpClient,
    *,
    season: str,
    season_type: str = "Regular Season",
    player_or_team: Literal["P", "T"] = "P",
    date_from: date | None = None,
    date_to: date | None = None,
    ttl: timedelta | None = None,
) -> list[dict[str, Any]]:
    """Fetch ``LeagueGameLog`` and return parsed rows from the first resultSet.

    Bulk historical: ``date_from`` and ``date_to`` left None.
    Daily incremental: pass yesterday's date for both.

    Pass ``ttl=None`` (the default) for settled historical data so the
    cache never expires. Pass a small TTL for current-season data that
    might shift as the league corrects stats.
    """
    params: dict[str, Any] = {
        "Counter": "1000",
        "DateFrom": date_from.isoformat() if date_from else "",
        "DateTo": date_to.isoformat() if date_to else "",
        "Direction": "DESC",
        "ISTRound": "",
        "LeagueID": "00",
        "PlayerOrTeam": player_or_team,
        "Season": season,
        "SeasonType": season_type,
        "Sorter": "DATE",
    }
    body = client.get(
        f"{_NBA_STATS_BASE}/leaguegamelog",
        params=params,
        headers=_NBA_HEADERS,
        ttl=ttl,
    )
    return _parse_result_set(body, 0)


def _int_or_zero(raw: Any) -> int:
    if raw is None or raw == "":
        return 0
    return int(raw)


def _int_or_none(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    return int(raw)


def player_game_log_row_to_orm(
    row: dict[str, Any],
    *,
    season: str,
    season_type: str,
) -> PlayerGameLog:
    """Convert one ``PlayerOrTeam='P'`` row into a ``PlayerGameLog``.

    Does not touch the DB. Caller is responsible for ensuring the
    referenced Player/Team/Game exist before adding to a session.
    """
    return PlayerGameLog(
        player_id=int(row["PLAYER_ID"]),
        game_id=str(row["GAME_ID"]),
        team_id=int(row["TEAM_ID"]),
        season=season,
        season_type=season_type,
        event_time=_event_time_from_game_date(str(row["GAME_DATE"])),
        minutes=_parse_minutes(row.get("MIN")),
        points=_int_or_zero(row.get("PTS")),
        rebounds=_int_or_zero(row.get("REB")),
        offensive_rebounds=_int_or_zero(row.get("OREB")),
        defensive_rebounds=_int_or_zero(row.get("DREB")),
        assists=_int_or_zero(row.get("AST")),
        steals=_int_or_zero(row.get("STL")),
        blocks=_int_or_zero(row.get("BLK")),
        turnovers=_int_or_zero(row.get("TOV")),
        personal_fouls=_int_or_zero(row.get("PF")),
        field_goals_made=_int_or_zero(row.get("FGM")),
        field_goals_attempted=_int_or_zero(row.get("FGA")),
        three_pointers_made=_int_or_zero(row.get("FG3M")),
        three_pointers_attempted=_int_or_zero(row.get("FG3A")),
        free_throws_made=_int_or_zero(row.get("FTM")),
        free_throws_attempted=_int_or_zero(row.get("FTA")),
        plus_minus=_int_or_none(row.get("PLUS_MINUS")),
        raw_data=row,
    )


def player_identity_from_row(row: dict[str, Any]) -> Player:
    """Extract a ``Player`` from any LeagueGameLog row."""
    return Player(
        player_id=int(row["PLAYER_ID"]),
        current_name=str(row["PLAYER_NAME"]),
    )


def team_identity_from_row(row: dict[str, Any]) -> Team:
    """Extract a ``Team`` from a T-level LeagueGameLog row.

    T-level rows have ``TEAM_CITY`` and ``TEAM_NAME`` as separate fields.
    P-level rows put the full display in ``TEAM_NAME``, which is ambiguous
    (e.g., "Portland Trail Blazers" doesn't split cleanly). Use T-level
    rows for team identity in the bulk loader; P-level rows are for
    ``player_game_logs`` only.
    """
    return Team(
        team_id=int(row["TEAM_ID"]),
        name=str(row.get("TEAM_NAME") or ""),
        city=str(row.get("TEAM_CITY") or ""),
        abbreviation=str(row.get("TEAM_ABBREVIATION") or ""),
    )


def _split_home_away(
    row_a: dict[str, Any],
    row_b: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (home_row, away_row) from a pair of T-level rows.

    NBA ``MATCHUP`` format: ``"LAL vs. BOS"`` (home) or ``"BOS @ LAL"`` (away).
    """
    matchup_a = str(row_a.get("MATCHUP", ""))
    if " vs. " in matchup_a:
        return row_a, row_b
    if " @ " in matchup_a:
        return row_b, row_a
    raise ValueError(f"Unrecognized MATCHUP: {matchup_a!r}")


def team_game_log_rows_to_orm(
    row_a: dict[str, Any],
    row_b: dict[str, Any],
    *,
    season: str,
    season_type: str,
) -> tuple[Game, GameResult]:
    """Pair of T-level rows for one ``GAME_ID`` → ``(Game, GameResult)``.

    Order of arguments doesn't matter; we figure out home/away from
    each row's ``MATCHUP`` string. Both rows must share ``GAME_ID``.
    """
    if row_a["GAME_ID"] != row_b["GAME_ID"]:
        raise ValueError(
            f"Rows must share GAME_ID; got {row_a['GAME_ID']!r} and {row_b['GAME_ID']!r}"
        )

    home_row, away_row = _split_home_away(row_a, row_b)

    game_id = str(home_row["GAME_ID"])
    game_date_str = str(home_row["GAME_DATE"])
    event_time = _event_time_from_game_date(game_date_str)

    game = Game(
        game_id=game_id,
        season=season,
        season_type=season_type,
        game_date=date.fromisoformat(game_date_str),
        scheduled_tip_time_utc=None,  # not in LeagueGameLog
        home_team_id=int(home_row["TEAM_ID"]),
        away_team_id=int(away_row["TEAM_ID"]),
        event_time=event_time,
    )

    result = GameResult(
        game_id=game_id,
        home_score=_int_or_zero(home_row.get("PTS")),
        away_score=_int_or_zero(away_row.get("PTS")),
        status="final",
        event_time=event_time,
        raw_data={"home": home_row, "away": away_row},
    )

    return game, result
