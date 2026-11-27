"""Score Haiku (or rule fallback) on the frozen held-out injury set.

uv run python -m app.data.injury.eval_heldout

The default frozen set is not a measurement of Haiku (template-expanded).
See docs/results/m7-llm.md. This scorer still refuses empty-player credit
and separates regex fallback from LLM success so a re-run cannot reprint
a fake 1.000 as Haiku accuracy.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from app.data.injury.classify import classify_item
from app.data.injury.sources import RawInjuryItem

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_SET = _REPO_ROOT / "docs" / "results" / "m7-llm-heldout.jsonl"
_DEFAULT_REPORT = _REPO_ROOT / "docs" / "results" / "m7-llm.md"

_INVALID_BANNER = (
    "INVALID — do not cite. The default frozen set is template-expanded, "
    "not a real held-out of scraped items. Empty player predictions and "
    "regex-only classifications are not LLM success."
)


def load_heldout(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def player_match(gold_player: str, pred_player: str) -> bool:
    """True only when both names are non-empty and one contains the other.

    An empty prediction must not count as correct (`'' in name` is True in
    Python and previously inflated held-out player accuracy to 1.000).
    """
    gold = gold_player.strip().lower()
    pred = pred_player.strip().lower()
    if not gold or not pred:
        return False
    return gold in pred or pred in gold


def is_llm_model(classifier_model: str) -> bool:
    """Regex / rule fallback is not Haiku success."""
    model = (classifier_model or "").strip().lower()
    if not model:
        return False
    if model.startswith("rule-based") or model == "regex" or "fallback" in model:
        return False
    return any(token in model for token in ("claude", "haiku", "sonnet", "anthropic"))


def evaluate(path: Path) -> dict[str, Any]:
    rows = load_heldout(path)
    correct_claim = 0
    correct_player = 0
    correct_both = 0
    llm_both = 0
    llm_n = 0
    details = []
    for row in rows:
        item = RawInjuryItem(
            source=row.get("source", "espn"),
            source_url=row.get("source_url"),
            title=row.get("title", ""),
            text=row["text"],
            event_time=__import__("datetime").datetime.fromisoformat(row["event_time"]),
            raw_data={"heldout_id": row["id"]},
        )
        classified = classify_item(item)
        claim_ok = classified.claim_type == row["claim_type"]
        gold_player = (row.get("player") or "").strip()
        pred_player = classified.player_name_raw
        player_ok = player_match(gold_player, pred_player)
        llm = is_llm_model(classified.classifier_model)
        if claim_ok:
            correct_claim += 1
        if player_ok:
            correct_player += 1
        if claim_ok and player_ok:
            correct_both += 1
        if llm:
            llm_n += 1
            if claim_ok and player_ok:
                llm_both += 1
        details.append(
            {
                "id": row["id"],
                "claim_ok": claim_ok,
                "player_ok": player_ok,
                "pred_claim": classified.claim_type,
                "pred_player": classified.player_name_raw,
                "model": classified.classifier_model,
                "is_llm": llm,
            }
        )
    n = len(rows) or 1
    llm_joint = (llm_both / llm_n) if llm_n else 0.0
    return {
        "n": len(rows),
        "claim_accuracy": correct_claim / n,
        "player_accuracy": correct_player / n,
        "joint_accuracy": correct_both / n,
        "llm_n": llm_n,
        "llm_joint_accuracy": llm_joint,
        "bar": 0.85,
        # Default frozen set is not a valid acceptance measurement.
        "passed": False,
        "invalid": True,
        "details": details,
    }


def write_report(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# M7 LLM held-out accuracy — INVALID",
        "",
        _INVALID_BANNER,
        "",
        f"- N = {result['n']}",
        f"- Joint accuracy (player + claim_type, all classifiers) = {result['joint_accuracy']:.3f}",
        f"- Claim accuracy = {result['claim_accuracy']:.3f}",
        f"- Player accuracy = {result['player_accuracy']:.3f}",
        f"- LLM-only N / joint = {result['llm_n']} / {result['llm_joint_accuracy']:.3f}",
        f"- Bar = {result['bar']:.2f}",
        f"- Passed = {result['passed']} (forced false while set is marked invalid)",
        "",
        "Frozen set: `docs/results/m7-llm-heldout.jsonl` (see `.NOTE.md`).",
        "Prompt version: `m7-injury-v1`.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heldout", type=Path, default=_DEFAULT_SET)
    parser.add_argument("--report", type=Path, default=_DEFAULT_REPORT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = evaluate(args.heldout)
    write_report(result, args.report)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "n",
                    "joint_accuracy",
                    "llm_n",
                    "llm_joint_accuracy",
                    "passed",
                    "invalid",
                    "bar",
                )
            },
            indent=2,
        )
    )
    return 1 if result.get("invalid") else (0 if result["passed"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
