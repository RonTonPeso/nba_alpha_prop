"""Source reliability priors and RSS / official scrape helpers."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Hard-coded priors for known outlets. Refine later from calibration.
SOURCE_RELIABILITY: dict[str, float] = {
    "nba_official": 0.95,
    "espn": 0.80,
    "bleacher_report": 0.70,
    "unknown": 0.50,
}

ESPN_NBA_RSS = "https://www.espn.com/espn/rss/nba/news"
# League-tagged BR feeds 404 as of 2025. Use the sitewide feed and keep
# items whose title/description mention NBA or basketball.
BR_NBA_RSS = "https://feeds.bleacherreport.com/articles"


@dataclass(frozen=True)
class RawInjuryItem:
    """One scraped news or report item before LLM classification."""

    source: str
    source_url: str | None
    title: str
    text: str
    event_time: datetime
    raw_data: dict[str, Any]


def reliability_for(source: str) -> float:
    return SOURCE_RELIABILITY.get(source, SOURCE_RELIABILITY["unknown"])


def _parse_rss_datetime(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (TypeError, ValueError, IndexError):
        return datetime.now(UTC)


def fetch_rss_feed(url: str, *, source: str, limit: int = 25) -> list[RawInjuryItem]:
    """Fetch and parse an RSS 2.0 feed into raw items."""
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "nba-alpha-prop/m7"})
        response.raise_for_status()
        body = response.text

    root = ET.fromstring(body)
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[RawInjuryItem] = []
    for item in channel.findall("item")[:limit]:
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        # Strip simple HTML tags from descriptions.
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip()
        link = (item.findtext("link") or "").strip() or None
        pub = item.findtext("pubDate")
        text = f"{title}. {description}".strip()
        if not title and not description:
            continue
        items.append(
            RawInjuryItem(
                source=source,
                source_url=link,
                title=title,
                text=text,
                event_time=_parse_rss_datetime(pub),
                raw_data={"feed_url": url, "title": title, "pubDate": pub},
            )
        )
    return items


def fetch_espn_rss(*, limit: int = 25) -> list[RawInjuryItem]:
    return fetch_rss_feed(ESPN_NBA_RSS, source="espn", limit=limit)


def fetch_bleacher_report_rss(*, limit: int = 25) -> list[RawInjuryItem]:
    items = fetch_rss_feed(BR_NBA_RSS, source="bleacher_report", limit=max(limit * 4, 40))
    nbaish = [
        item
        for item in items
        if re.search(r"\b(nba|lakers|celtics|knicks|warriors|basketball)\b", item.text, re.I)
    ]
    return nbaish[:limit]


def fetch_official_report(
    report_time: datetime | None = None,
) -> list[RawInjuryItem]:
    """Pull the official NBA injury report via ``nbainjuries``.

    ``report_time`` is Eastern local wall time as the package expects.
    Returns an empty list when the package, Java, or the report is
    unavailable so RSS can still prove the pipeline.
    """
    try:
        from nbainjuries import injury
    except Exception:
        logger.exception("nbainjuries unavailable (import or JVM); skipping official report")
        return []

    # Default: today 17:30 ET-ish as a naive datetime (package docs).
    if report_time is None:
        now = datetime.now()
        report_time = now.replace(hour=17, minute=30, second=0, microsecond=0)

    try:
        valid = injury.check_reportvalid(report_time)
    except Exception:
        logger.exception("official report validity check failed")
        return []
    if not valid:
        logger.info("no official injury report at %s", report_time)
        return []

    try:
        payload = injury.get_reportdata(report_time, return_df=False)
    except Exception:
        logger.exception("official report fetch failed at %s", report_time)
        return []

    rows: list[dict[str, Any]]
    if isinstance(payload, list):
        rows = [r for r in payload if isinstance(r, dict)]
    elif isinstance(payload, dict):
        maybe = payload.get("data") or payload.get("rows") or []
        rows = [r for r in maybe if isinstance(r, dict)] if isinstance(maybe, list) else []
    else:
        rows = []

    # Treat report_time as America/New_York wall clock → UTC approx via -5/-4
    # is fragile; store as UTC-tagged naive converted with replace.
    event_time = report_time.replace(tzinfo=UTC)
    items: list[RawInjuryItem] = []
    for row in rows:
        name = str(
            row.get("Player Name")
            or row.get("player_name")
            or row.get("PLAYER_NAME")
            or row.get("player")
            or ""
        ).strip()
        status = str(
            row.get("Current Status") or row.get("current_status") or row.get("status") or ""
        ).strip()
        reason = str(row.get("Reason") or row.get("reason") or row.get("injury") or "").strip()
        team = str(row.get("Team") or row.get("team") or "").strip()
        if not name and not status:
            continue
        text = f"{name} ({team}): {status}. {reason}".strip()
        items.append(
            RawInjuryItem(
                source="nba_official",
                source_url=None,
                title=f"{name} {status}".strip(),
                text=text,
                event_time=event_time,
                raw_data={"report_time": report_time.isoformat(), "row": row},
            )
        )
    return items
