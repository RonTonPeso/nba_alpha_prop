"""Test doubles for the HTTP client injected into ``CachedHttpClient``.

Production uses ``curl_cffi.requests.Session`` (impersonates Chrome's TLS
fingerprint so Akamai's bot manager lets requests through). Tests inject
``FakeSession`` instead, which calls a user-supplied handler.

The handler signature is ``(url, params, headers) -> FakeResponse`` or it
may raise (e.g., ``curl_cffi.requests.exceptions.Timeout``) to simulate
network failures.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from curl_cffi.requests.exceptions import HTTPError


@dataclass
class FakeResponse:
    """Minimal stand-in for a curl_cffi Response object."""

    status_code: int
    body: Any = None
    raise_on_json: bool = False

    def json(self) -> Any:
        if self.raise_on_json:
            import json as _json

            raise _json.JSONDecodeError("simulated decode error", "", 0)
        return self.body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"HTTP {self.status_code}")


Handler = Callable[[str, dict[str, Any], dict[str, str]], FakeResponse]


@dataclass
class FakeSession:
    """Stand-in for ``curl_cffi.requests.Session``. Tracks call count."""

    handler: Handler
    call_count: int = 0
    calls: list[tuple[str, dict[str, Any], dict[str, str]]] = field(default_factory=list)

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> FakeResponse:
        self.call_count += 1
        params_norm = dict(params or {})
        headers_norm = dict(headers or {})
        self.calls.append((url, params_norm, headers_norm))
        return self.handler(url, params_norm, headers_norm)

    def close(self) -> None:
        pass
