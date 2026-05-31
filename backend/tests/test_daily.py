"""Tests for the daily ingestion job.

Two surfaces:
1. ``current_season`` maps a calendar date to the right NBA season string.
2. ``run_daily_ingest`` opens a session, calls ``load_season`` with
   ``date_from=date_to=yesterday``, and the rows land in the DB.

The session-opening path is tested indirectly via ``load_season`` (which
``run_daily_ingest`` delegates to); we don't unit-test the daily wrapper
end-to-end because it'd require monkey-patching the engine. The
``load_season(..., date_from=, date_to=)`` path itself is the
load-with-date-filter behavior the daily job depends on.
"""

from datetime import date
from typing import Any

from sqlmodel import Session, select

from app.data.bulk_load import load_season
from app.data.cache import CachedHttpClient
from app.data.daily import current_season
from app.db.tables import PlayerGameLog
from tests._fakes import FakeResponse, FakeSession


def test_current_season_october_starts_new_season() -> None:
    assert current_season(date(2024, 10, 22)) == "2024-25"


def test_current_season_march_is_prior_year_season() -> None:
    assert current_season(date(2025, 3, 15)) == "2024-25"


def test_current_season_july_is_new_season() -> None:
    # Cutoff is July 1: anything in July onward → new season.
    assert current_season(date(2024, 7, 1)) == "2024-25"
    assert current_season(date(2024, 6, 30)) == "2023-24"


def test_current_season_century_boundary() -> None:
    assert current_season(date(2099, 10, 22)) == "2099-00"


def test_load_season_passes_date_filters_to_fetch(db_session: Session) -> None:
    """Daily ingest's core: load_season called with date_from=date_to=yesterday
    forwards those filters into the LeagueGameLog params."""
    requests_seen: list[dict[str, Any]] = []

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        requests_seen.append(params)
        body: dict[str, Any] = {"resultSets": [{"headers": [], "rowSet": []}]}
        return FakeResponse(200, body)

    session = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=session)

    yesterday = date(2024, 12, 14)
    summary = load_season(
        cache,
        db_session,
        season="2024-25",
        season_type="Regular Season",
        date_from=yesterday,
        date_to=yesterday,
    )

    # Two requests: one T, one P. Both should carry the date filters.
    assert len(requests_seen) == 2
    for req_params in requests_seen:
        assert req_params["DateFrom"] == "2024-12-14"
        assert req_params["DateTo"] == "2024-12-14"

    # Empty response → zero new rows.
    assert summary.t_rows == 0
    assert summary.p_rows == 0
    assert summary.pgls_inserted == 0

    pgls = list(db_session.exec(select(PlayerGameLog)).all())
    assert len(pgls) == 0
