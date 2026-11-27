"""Claude Haiku structured classification for injury news items."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from app.data.injury.sources import RawInjuryItem, reliability_for

logger = logging.getLogger(__name__)

PROMPT_VERSION = "m7-injury-v1"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
FALLBACK_MODEL = "claude-sonnet-4-5-20250929"
# Silent offline / API-error path. Stored for audit; must not arm lineup trigger.
REGEX_FALLBACK_MODEL = "rule-based-m7"


def is_regex_fallback_model(classifier_model: str | None) -> bool:
    model = (classifier_model or "").strip().lower()
    return model == REGEX_FALLBACK_MODEL or model.startswith("rule-based")


CLAIM_TYPES = frozenset(
    {
        "out",
        "doubtful",
        "questionable",
        "probable",
        "available",
        "rest",
        "return",
        "unrelated",
        "unknown",
    }
)

_SYSTEM = """You classify NBA injury and availability news into one JSON object.
Return ONLY valid JSON with these keys:
player (string, best full name or empty),
claim_type (out|doubtful|questionable|probable|available|rest|return|unrelated|unknown),
severity (short string or null),
expected_games_missed (number or null),
confidence (number from 0 to 1).
If the item is not about a player's availability, use claim_type unrelated.
"""


@dataclass(frozen=True)
class ClassifiedInjury:
    player_name_raw: str
    claim_type: str
    severity: str | None
    expected_games_missed: float | None
    source: str
    source_reliability_prior: float
    confidence: float
    source_url: str | None
    raw_text: str
    classifier_model: str
    prompt_version: str
    raw_data: dict[str, Any]


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("classifier JSON root must be an object")
    return parsed


def _rule_based_classify(item: RawInjuryItem) -> ClassifiedInjury:
    """Deterministic fallback when no API key is set (tests / offline)."""
    lower = item.text.lower()
    claim = "unrelated"
    confidence = 0.55
    if re.search(r"\bout\b", lower):
        claim = "out"
        confidence = 0.7
    elif "doubtful" in lower:
        claim = "doubtful"
        confidence = 0.65
    elif "questionable" in lower:
        claim = "questionable"
        confidence = 0.65
    elif "probable" in lower:
        claim = "probable"
        confidence = 0.6
    elif "return" in lower or "cleared" in lower:
        claim = "return"
        confidence = 0.6
    elif re.search(r"\brest\b", lower):
        claim = "rest"
        confidence = 0.6
    elif "available" in lower:
        claim = "available"
        confidence = 0.6
    elif not re.search(
        r"\b(out|doubtful|questionable|probable|injury|ankle|knee|wrist)\b",
        lower,
    ):
        claim = "unrelated"
        confidence = 0.7

    # Prefer "First Last" before a colon or status word.
    name_match = re.match(
        r"^\s*([A-Z][a-z]+(?:\s[A-Z][a-z'\.]+)+)",
        item.title or item.text,
    )
    player = name_match.group(1) if name_match else ""
    return ClassifiedInjury(
        player_name_raw=player,
        claim_type=claim,
        severity=None,
        expected_games_missed=None,
        source=item.source,
        source_reliability_prior=reliability_for(item.source),
        confidence=confidence,
        source_url=item.source_url,
        raw_text=item.text,
        classifier_model=REGEX_FALLBACK_MODEL,
        prompt_version=PROMPT_VERSION,
        raw_data={"item": item.raw_data, "mode": "regex_fallback"},
    )


def classify_item(
    item: RawInjuryItem,
    *,
    model: str = DEFAULT_MODEL,
    client: Any | None = None,
    allow_rule_fallback: bool = True,
) -> ClassifiedInjury:
    """Classify one raw item with Haiku, or rule-based if no API key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        if not allow_rule_fallback:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        return _rule_based_classify(item)

    if client is None:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

    user = (
        f"Source: {item.source}\n"
        f"URL: {item.source_url or ''}\n"
        f"Title: {item.title}\n"
        f"Text: {item.text}\n"
    )
    try:
        message = client.messages.create(
            model=model,
            max_tokens=300,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
    except Exception:
        logger.exception("anthropic classify failed; using rule fallback")
        if allow_rule_fallback:
            return _rule_based_classify(item)
        raise

    text_parts: list[str] = []
    for block in message.content:
        block_type = getattr(block, "type", None)
        block_text = getattr(block, "text", None)
        if block_type == "text" and isinstance(block_text, str):
            text_parts.append(block_text)
    parsed = _extract_json("\n".join(text_parts))
    claim = str(parsed.get("claim_type") or "unknown").lower().strip()
    if claim not in CLAIM_TYPES:
        claim = "unknown"
    confidence = float(parsed.get("confidence") or 0.5)
    confidence = min(1.0, max(0.0, confidence))
    egm = parsed.get("expected_games_missed")
    expected: float | None
    try:
        expected = float(egm) if egm is not None else None
    except (TypeError, ValueError):
        expected = None
    severity = parsed.get("severity")
    severity_s = str(severity) if severity is not None else None
    player = str(parsed.get("player") or "").strip()

    # Low-confidence Sonnet fallback (Roadmap branch point).
    used_model = model
    if confidence < 0.5 and model == DEFAULT_MODEL:
        try:
            return classify_item(
                item,
                model=FALLBACK_MODEL,
                client=client,
                allow_rule_fallback=False,
            )
        except Exception:
            logger.exception("sonnet fallback failed; keeping haiku result")

    return ClassifiedInjury(
        player_name_raw=player,
        claim_type=claim,
        severity=severity_s,
        expected_games_missed=expected,
        source=item.source,
        source_reliability_prior=reliability_for(item.source),
        confidence=confidence,
        source_url=item.source_url,
        raw_text=item.text,
        classifier_model=used_model,
        prompt_version=PROMPT_VERSION,
        raw_data={
            "item": item.raw_data,
            "llm": parsed,
            "model": used_model,
        },
    )
