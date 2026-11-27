"""Scrape → classify → store injury_signals."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.data.injury.classify import ClassifiedInjury, classify_item
from app.data.injury.sources import (
    RawInjuryItem,
    fetch_bleacher_report_rss,
    fetch_espn_rss,
    fetch_official_report,
)
from app.db.tables import InjurySignal, KalshiPlayerAlias, Player

logger = logging.getLogger(__name__)


def _norm_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def build_player_name_map(session: Session) -> dict[str, int]:
    """Map normalized display names and Kalshi aliases to player_id."""
    mapping: dict[str, int] = {}
    for player in session.exec(select(Player)).all():
        mapping[_norm_name(player.current_name)] = player.player_id
    for alias in session.exec(select(KalshiPlayerAlias)).all():
        mapping[_norm_name(alias.kalshi_player_name)] = alias.player_id
    return mapping


def resolve_player_id(name: str, name_map: dict[str, int]) -> int | None:
    if not name.strip():
        return None
    key = _norm_name(name)
    if key in name_map:
        return name_map[key]
    # Last-token fallback when unique.
    last = key.split()[-1] if key.split() else ""
    if not last:
        return None
    matches = [pid for norm, pid in name_map.items() if norm.endswith(" " + last)]
    if len(set(matches)) == 1:
        return matches[0]
    return None


@dataclass
class PipelineSummary:
    scraped: int = 0
    classified: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    unresolved_player: int = 0
    seconds: float | None = None
    errors: list[str] = field(default_factory=list)


def _already_stored(session: Session, item: RawInjuryItem, classified: ClassifiedInjury) -> bool:
    if item.source_url:
        existing = session.exec(
            select(InjurySignal).where(InjurySignal.source_url == item.source_url)
        ).first()
        if existing is not None:
            return True
    # Official rows often lack URL; dedupe on text + event_time.
    existing = session.exec(
        select(InjurySignal).where(
            InjurySignal.raw_text == classified.raw_text,
            InjurySignal.event_time == item.event_time,
            InjurySignal.source == classified.source,
        )
    ).first()
    return existing is not None


def store_classified(
    session: Session,
    item: RawInjuryItem,
    classified: ClassifiedInjury,
    *,
    name_map: dict[str, int],
    available_at: datetime | None = None,
) -> InjurySignal | None:
    if _already_stored(session, item, classified):
        return None
    now = datetime.now(UTC)
    player_id = resolve_player_id(classified.player_name_raw, name_map)
    row = InjurySignal(
        player_id=player_id,
        player_name_raw=classified.player_name_raw or item.title[:120],
        claim_type=classified.claim_type,
        severity=classified.severity,
        expected_games_missed=classified.expected_games_missed,
        source=classified.source,
        source_reliability_prior=classified.source_reliability_prior,
        confidence=classified.confidence,
        source_url=classified.source_url,
        raw_text=classified.raw_text,
        event_time=(
            item.event_time if item.event_time.tzinfo else item.event_time.replace(tzinfo=UTC)
        ),
        available_at=available_at or now,
        ingested_at=now,
        classifier_model=classified.classifier_model,
        prompt_version=classified.prompt_version,
        raw_data=classified.raw_data,
    )
    session.add(row)
    return row


def collect_raw_items(
    *,
    include_official: bool = True,
    include_rss: bool = True,
    rss_limit: int = 15,
    official_time: datetime | None = None,
) -> list[RawInjuryItem]:
    items: list[RawInjuryItem] = []
    if include_official:
        try:
            items.extend(fetch_official_report(official_time))
        except Exception:
            logger.exception("official scrape failed")
    if include_rss:
        for fetcher in (fetch_espn_rss, fetch_bleacher_report_rss):
            try:
                items.extend(fetcher(limit=rss_limit))
            except Exception:
                logger.exception("rss scrape failed for %s", fetcher.__name__)
    return items


def run_injury_pipeline(
    session: Session,
    *,
    include_official: bool = True,
    include_rss: bool = True,
    rss_limit: int = 15,
    max_classify: int | None = 40,
    classify_fn: Any = classify_item,
    official_time: datetime | None = None,
    raw_items: list[RawInjuryItem] | None = None,
) -> PipelineSummary:
    summary = PipelineSummary()
    items = (
        raw_items
        if raw_items is not None
        else collect_raw_items(
            include_official=include_official,
            include_rss=include_rss,
            rss_limit=rss_limit,
            official_time=official_time,
        )
    )
    summary.scraped = len(items)
    if max_classify is not None:
        items = items[:max_classify]

    name_map = build_player_name_map(session)
    for item in items:
        try:
            classified = classify_fn(item)
        except Exception as exc:
            summary.errors.append(str(exc))
            continue
        summary.classified += 1
        row = store_classified(session, item, classified, name_map=name_map)
        if row is None:
            summary.skipped_duplicate += 1
            continue
        if row.player_id is None and classified.claim_type != "unrelated":
            summary.unresolved_player += 1
        summary.inserted += 1
    session.commit()
    return summary
