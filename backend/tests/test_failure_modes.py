"""The four ingestion failure modes per M1 acceptance criteria.

Each test maps to one criterion from docs/Roadmap.md M1:

1. **Timeout** — cache propagates ``curl_cffi`` ``Timeout``, does NOT
   write a row. Caller decides on retry policy.
2. **429 rate limit** — cache propagates ``HTTPError`` (because
   ``raise_for_status()`` runs before ``_store``), does NOT write a row.
3. **Malformed JSON** — cache propagates the JSON decode error, does
   NOT write a row.
4. **Missing field / upstream schema drift** — ``load_season`` skips
   the unparseable row, logs a warning, bumps ``pgls_errors``, and
   continues with the rest of the season.

The first three live at the network layer (``CachedHttpClient``). The
fourth lives at the orchestration layer (``load_season``) because that's
where per-row skip-and-continue policy lives.
"""

import json
from typing import Any

import pytest
from curl_cffi.requests.exceptions import HTTPError, Timeout
from sqlmodel import Session, select

from app.data.bulk_load import load_season
from app.data.cache import CachedHttpClient, _compute_keys
from app.db.tables import PlayerGameLog, RequestCache
from tests._fakes import FakeResponse, FakeSession

# ----- 1. Timeout -----


def test_cache_propagates_timeout_and_does_not_store(db_session: Session) -> None:
    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        raise Timeout("simulated")

    session = FakeSession(handler)
    # max_retries=0 so we don't burn through the backoff schedule in tests.
    cache = CachedHttpClient(db_session, client=session, max_retries=0)

    with pytest.raises(Timeout):
        cache.get("https://example.com/timeout", params={"x": 1})

    cache_key, _ = _compute_keys("https://example.com/timeout", {"x": 1})
    assert db_session.get(RequestCache, cache_key) is None


def test_cache_retries_on_timeout_then_succeeds(db_session: Session) -> None:
    """First two attempts time out, third succeeds. Verifies retry loop."""
    attempts = [0]

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        attempts[0] += 1
        if attempts[0] < 3:
            raise Timeout("simulated")
        return FakeResponse(200, {"ok": True})

    session = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=session, max_retries=3, retry_backoff_seconds=0.0)

    body = cache.get("https://example.com/flaky")
    assert body == {"ok": True}
    assert attempts[0] == 3


# ----- 2. 429 rate limit -----


def test_cache_propagates_429_and_does_not_store(db_session: Session) -> None:
    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        return FakeResponse(429, {"error": "rate limited"})

    session = FakeSession(handler)
    # max_retries=0 so we don't sleep through the backoff schedule.
    cache = CachedHttpClient(db_session, client=session, max_retries=0)

    with pytest.raises(HTTPError):
        cache.get("https://example.com/limited")

    cache_key, _ = _compute_keys("https://example.com/limited", None)
    assert db_session.get(RequestCache, cache_key) is None


def test_cache_retries_on_429_then_succeeds(db_session: Session) -> None:
    """First two attempts 429, third returns 200. Verifies the 429 retry loop."""
    attempts = [0]

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        attempts[0] += 1
        if attempts[0] < 3:
            return FakeResponse(429, {"error": "rate limited"})
        return FakeResponse(200, {"ok": True})

    session = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=session, max_retries=3, retry_backoff_seconds=0.0)

    body = cache.get("https://example.com/sometimes-limited")
    assert body == {"ok": True}
    assert attempts[0] == 3


# ----- 3. Malformed JSON -----


def test_cache_propagates_malformed_json_and_does_not_store(db_session: Session) -> None:
    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        return FakeResponse(200, raise_on_json=True)

    session = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=session)

    with pytest.raises((json.JSONDecodeError, ValueError)):
        cache.get("https://example.com/garbage")

    cache_key, _ = _compute_keys("https://example.com/garbage", None)
    assert db_session.get(RequestCache, cache_key) is None


# ----- 4. Missing field / upstream schema drift -----


def test_load_season_skips_pgl_rows_with_missing_player_id(db_session: Session) -> None:
    """If a P-row has null PLAYER_ID, load_season logs and continues."""
    t_body = {
        "resultSets": [
            {
                "headers": [
                    "TEAM_ID",
                    "TEAM_NAME",
                    "TEAM_CITY",
                    "TEAM_ABBREVIATION",
                    "GAME_ID",
                    "GAME_DATE",
                    "MATCHUP",
                    "PTS",
                ],
                "rowSet": [
                    [
                        1610612747,
                        "Lakers",
                        "Los Angeles",
                        "LAL",
                        "0099900001",
                        "2024-10-22",
                        "LAL vs. BOS",
                        110,
                    ],
                    [
                        1610612738,
                        "Celtics",
                        "Boston",
                        "BOS",
                        "0099900001",
                        "2024-10-22",
                        "BOS @ LAL",
                        105,
                    ],
                ],
            }
        ]
    }
    p_body = {
        "resultSets": [
            {
                "headers": [
                    "PLAYER_ID",
                    "PLAYER_NAME",
                    "TEAM_ID",
                    "GAME_ID",
                    "GAME_DATE",
                    "MIN",
                    "PTS",
                ],
                "rowSet": [
                    [2544, "Good Player", 1610612747, "0099900001", "2024-10-22", "34:00", 25],
                    [None, "Bad Player", 1610612738, "0099900001", "2024-10-22", "30:00", 18],
                ],
            }
        ]
    }

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        if params.get("PlayerOrTeam") == "T":
            return FakeResponse(200, t_body)
        return FakeResponse(200, p_body)

    session = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=session)

    summary = load_season(cache, db_session, season="2024-25", season_type="Regular Season")

    assert summary.pgls_inserted == 1
    assert summary.pgls_errors == 1
    assert summary.pgls_skipped == 0

    pgls = list(db_session.exec(select(PlayerGameLog)).all())
    assert len(pgls) == 1
    assert pgls[0].player_id == 2544
