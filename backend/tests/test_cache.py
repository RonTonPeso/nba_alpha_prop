"""Tests for the Postgres-backed HTTP cache wrapper.

Three behaviors verified:
1. A cache miss fetches, stores, and returns the body.
2. A cache hit returns the stored body without calling the network.
3. An expired row triggers a refetch.

Plus one micro-test for cache key determinism.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session

from app.data.cache import CachedHttpClient, _compute_keys
from app.db.tables import RequestCache
from tests._fakes import FakeResponse, FakeSession


def test_cache_key_is_deterministic_and_param_order_independent() -> None:
    key_a, _ = _compute_keys("https://example.com", {"a": 1, "b": 2})
    key_b, _ = _compute_keys("https://example.com", {"b": 2, "a": 1})
    key_c, _ = _compute_keys("https://example.com", {"a": 1, "b": 3})
    assert key_a == key_b
    assert key_a != key_c


def test_cache_miss_fetches_and_stores(db_session: Session) -> None:
    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        return FakeResponse(200, {"hello": "world"})

    session = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=session)

    body = cache.get("https://example.com/data", params={"x": 1})

    assert body == {"hello": "world"}
    assert session.call_count == 1

    cache_key, _ = _compute_keys("https://example.com/data", {"x": 1})
    row = db_session.get(RequestCache, cache_key)
    assert row is not None
    assert row.url == "https://example.com/data"
    assert row.response_body == {"hello": "world"}
    assert row.status_code == 200
    assert row.expires_at is None


def test_cache_hit_does_not_call_network(db_session: Session) -> None:
    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        return FakeResponse(200, {"called": True})

    session = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=session)

    cache.get("https://example.com/x")
    assert session.call_count == 1

    body = cache.get("https://example.com/x")
    assert body == {"called": True}
    assert session.call_count == 1  # no second network call


def test_expired_cache_triggers_refetch(db_session: Session) -> None:
    bodies = [{"v": 1}, {"v": 2}]
    counter = [0]

    def handler(url: str, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        counter[0] += 1
        return FakeResponse(200, bodies[counter[0] - 1])

    session = FakeSession(handler)
    cache = CachedHttpClient(db_session, client=session)

    body1 = cache.get("https://example.com/y", ttl=timedelta(seconds=60))
    assert body1 == {"v": 1}
    assert counter[0] == 1

    cache_key, _ = _compute_keys("https://example.com/y", None)
    row = db_session.get(RequestCache, cache_key)
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    body2 = cache.get("https://example.com/y", ttl=timedelta(seconds=60))
    assert body2 == {"v": 2}
    assert counter[0] == 2
