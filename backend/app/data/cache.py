"""Postgres-backed HTTP cache for outbound API calls.

``stats.nba.com`` rate-limits hard, and bulk historical loads make many
calls before. The cache means we never fetch the same
``(url, params)`` twice unless expired, and an unfinished or partial load
can restart without going to the API again.

All outbound NBA / Kalshi calls go through this client.

Implementation note: the underlying HTTP client is ``curl_cffi``, not
``httpx``. ``stats.nba.com`` sits behind Akamai's bot manager which
fingerprints TLS handshakes and silently drops anything that doesn't
look like a real browser. ``httpx`` (and ``requests``, and plain curl,
and the ``nba_api`` library) all get blocked. ``curl_cffi`` impersonates
Chrome's TLS handshake and passes Akamai's check. See ``docs/adr.md``
"TLS fingerprinting" for the full story.
"""

import hashlib
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self

from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import Timeout as CurlTimeout
from sqlmodel import Session

from app.db.tables import RequestCache

logger = logging.getLogger(__name__)


def _compute_keys(url: str, params: dict[str, Any] | None) -> tuple[str, str]:
    """Deterministic (cache_key, params_hash) from sha256 of sorted JSON."""
    params_json = json.dumps(params or {}, sort_keys=True, default=str)
    params_hash = hashlib.sha256(params_json.encode()).hexdigest()[:16]
    cache_key = hashlib.sha256(f"{url}|{params_json}".encode()).hexdigest()
    return cache_key, params_hash


class CachedHttpClient:
    """Synchronous HTTP client with Postgres-backed response cache.

    On every ``get()``:
    1. Hash ``(url, sorted params)`` into ``cache_key``.
    2. Look up ``request_cache``. If present and not expired, return cached body.
    3. Otherwise fetch with curl_cffi, store the 200 response, return parsed body.

    Only 200 responses are cached. Non-200 gives ``HTTPError``.
    """

    def __init__(
        self,
        session: Session,
        *,
        default_ttl: timedelta | None = None,
        timeout: float = 90.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 2.0,
        client: Any | None = None,
    ) -> None:
        self._session = session
        self._default_ttl = default_ttl
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        # chrome120 is a Chrome TLS fingerprint that curl_cffi ships and Akamai
        # currently accepts as legitimate. See docs/adr.md for the full story.
        if client is None:
            client = curl_requests.Session(impersonate="chrome120")
            self._owns_client = True
        else:
            self._owns_client = False
        self._http_client = client

    def close(self) -> None:
        if self._owns_client:
            self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        ttl: timedelta | None = None,
    ) -> Any:
        cache_key, params_hash = _compute_keys(url, params)

        cached = self._lookup(cache_key)
        if cached is not None:
            return cached

        response = self._fetch_with_retry(url, params, headers)
        response.raise_for_status()
        body = response.json()

        effective_ttl = ttl if ttl is not None else self._default_ttl
        self._store(
            cache_key=cache_key,
            url=url,
            params_hash=params_hash,
            response_body=body,
            status_code=response.status_code,
            ttl=effective_ttl,
        )

        return body

    def _fetch_with_retry(
        self,
        url: str,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
    ) -> Any:
        """Retry on timeout or HTTP 429.

        Exponential backoff: 2s, 4s, 8s for default retry_backoff_seconds=2.

        - Timeout: stats.nba.com is sometimes slow even via curl_cffi.
        - 429: Kalshi rate-limits transiently; backoff usually clears it.

        Other HTTP errors (4xx/5xx, JSONDecodeError) are NOT retried; they
        usually indicate something structural rather than transient.
        """
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http_client.get(
                    url, params=params, headers=headers, timeout=self._timeout
                )
            except CurlTimeout:
                if attempt >= self._max_retries:
                    raise
                delay = self._retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "Timeout fetching %s; retrying in %.1fs (attempt %d/%d)",
                    url,
                    delay,
                    attempt + 1,
                    self._max_retries + 1,
                )
                time.sleep(delay)
                continue

            if response.status_code == 429 and attempt < self._max_retries:
                delay = self._retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "HTTP 429 from %s; retrying in %.1fs (attempt %d/%d)",
                    url,
                    delay,
                    attempt + 1,
                    self._max_retries + 1,
                )
                time.sleep(delay)
                continue

            return response
        raise RuntimeError("unreachable")  # pragma: no cover

    def _lookup(self, cache_key: str) -> Any:
        row = self._session.get(RequestCache, cache_key)
        if row is None:
            return None
        if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
            return None
        return row.response_body

    def _store(
        self,
        *,
        cache_key: str,
        url: str,
        params_hash: str,
        response_body: Any,
        status_code: int,
        ttl: timedelta | None,
    ) -> None:
        now = datetime.now(UTC)
        expires_at = now + ttl if ttl is not None else None
        existing = self._session.get(RequestCache, cache_key)
        if existing is not None:
            existing.response_body = response_body
            existing.status_code = status_code
            existing.fetched_at = now
            existing.expires_at = expires_at
        else:
            self._session.add(
                RequestCache(
                    cache_key=cache_key,
                    url=url,
                    params_hash=params_hash,
                    response_body=response_body,
                    status_code=status_code,
                    fetched_at=now,
                    expires_at=expires_at,
                )
            )
        self._session.flush()
