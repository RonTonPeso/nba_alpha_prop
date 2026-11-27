"""Display preference among stored prediction model versions."""

from __future__ import annotations

# First match wins for a (player, game, prop) cell.
PREFERRED_VERSIONS: tuple[str, ...] = (
    "lineup-m7-v1",
    "pymc-m6-v1",
    "xgb-m5-v1",
    "baseline-m3-v1",
)


def prefer_version(available: set[str]) -> str | None:
    for version in PREFERRED_VERSIONS:
        if version in available:
            return version
    return None
