"""Score Haiku (or rule fallback) on the frozen held-out injury set.

uv run python -m app.data.injury.eval_heldout
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


def evaluate(path: Path) -> dict[str, Any]:
    rows = load_heldout(path)
    correct_claim = 0
    correct_player = 0
    correct_both = 0
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
        gold_player = (row.get("player") or "").strip().lower()
        pred_player = classified.player_name_raw.strip().lower()
        player_ok = (not gold_player) or (gold_player in pred_player or pred_player in gold_player)
        if claim_ok:
            correct_claim += 1
        if player_ok:
            correct_player += 1
        if claim_ok and player_ok:
            correct_both += 1
        details.append(
            {
                "id": row["id"],
                "claim_ok": claim_ok,
                "player_ok": player_ok,
                "pred_claim": classified.claim_type,
                "pred_player": classified.player_name_raw,
                "model": classified.classifier_model,
            }
        )
    n = len(rows) or 1
    return {
        "n": len(rows),
        "claim_accuracy": correct_claim / n,
        "player_accuracy": correct_player / n,
        "joint_accuracy": correct_both / n,
        "bar": 0.85,
        "passed": (correct_both / n) >= 0.85,
        "details": details,
    }


def write_report(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# M7 LLM held-out accuracy",
        "",
        f"- N = {result['n']}",
        f"- Joint accuracy (player + claim_type) = {result['joint_accuracy']:.3f}",
        f"- Claim accuracy = {result['claim_accuracy']:.3f}",
        f"- Player accuracy = {result['player_accuracy']:.3f}",
        f"- Bar = {result['bar']:.2f}",
        f"- Passed = {result['passed']}",
        "",
        "Frozen set: `docs/results/m7-llm-heldout.jsonl`.",
        "Prompt version: `m7-injury-v1`. Default model: Haiku 4.5.",
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
            {k: result[k] for k in ("n", "joint_accuracy", "passed", "bar")},
            indent=2,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
