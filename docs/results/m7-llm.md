# M7 LLM held-out accuracy — INVALID

**Do not cite.** This file previously reported joint/claim/player accuracy
1.000 on 100 rows. That number is not a measurement of Haiku.

Why it is invalid (M5–M8 retrospective review, M7 B1):

- The frozen set in `docs/results/m7-llm-heldout.jsonl` is template-expanded
  synthetic text, not a held-out sample of real RSS or official items.
- Empty `player_name` predictions were scored as correct (`"" in name`).
- Silent regex fallback (`rule-based-m7`) can match the templates and was
  reported as if it were the default Haiku model.

Prior printed metrics (retracted):

- N = 100
- Joint / claim / player accuracy = 1.000
- Bar = 0.85, Passed = True
- Claimed model: Claude Haiku 4.5, prompt `m7-injury-v1`

A real held-out from scraped sources was not rebuilt on this branch
(feedback-fixes: A + retract). Re-run
`uv run python -m app.data.injury.eval_heldout` only after replacing the
frozen set; the scorer no longer grants credit for empty player names or
regex-only classifications when scoring LLM success.
