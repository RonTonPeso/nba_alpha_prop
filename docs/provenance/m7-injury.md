# M7 results: injury signals and lineup redistribution

Written 27 Nov 2026 after the proving commands. The plan is
`docs/provenance/m7-plan.md`.

## Acceptance quotes aimed at

`docs/Roadmap.md` M7:

- An injury news item is classified and stored with structured fields
  within 5 minutes of being scraped.
- A simulated "Embiid out" event causes Maxey's projection to update
  meaningfully (synthetic; direction and magnitude).
- LLM classification accuracy on a held-out test set is documented.

## Commands run

```bash
cd backend
uv run alembic upgrade head
uv run python -m app.data.starter_backfill --start 2022-10-18 --end 2026-06-13 --team PHI --sleep 0.35
uv run python -m app.data.injury.run --timed --rss-limit 10 --max-classify 20
uv run python -m app.models.lineup_fit
uv run python -m app.models.lineup_apply --synthetic-embiid-maxey
uv run python -m app.data.injury.eval_heldout
uv run pytest tests/test_scheduler.py tests/test_lineup.py tests/test_injury.py -q
```

## Evidence

### Starter backfill (labels)

- PHI games seen/fetched: 358 / 358, failed 0.
- `player_game_logs.started` non-null: 5,888.
- Embiid starts flagged: 149. Maxey starts flagged: 193.
- Usual-starter rule locked at window 10, min starts 6.

Rejected for this close: league-wide backfill of every team. PHI alone
supplies the Embiid→Maxey cell the acceptance test names. Other teams
can be filled later without changing the model code.

### Timed scrape → classify → store

From `docs/results/m7-injury-timed.json`:

- scraped 10, classified 9, inserted 9
- wall-clock 14.67 seconds (under 300)
- ESPN RSS answered. Official `nbainjuries` import failed: JVM DLL
  path for AdoptOpenJDK 8 was missing (`libjli.dylib`). Pipeline
  continued. Bleacher Report league tag feed 404'd; switched to
  `https://feeds.bleacherreport.com/articles` with an NBA keyword
  filter (documented in ADR-5 / sources.py).

### Lineup fit and synthetic Embiid → Maxey

From `uv run python -m app.models.lineup_fit` and
`lineup_apply --synthetic-embiid-maxey`:

- `n_effects` = 1,296
- Embiid→Maxey points delta = +3.2716 (shrunk mean difference)
- Base Maxey mean 25.189 → 28.461 (lift 3.272 ≥ floor 1.636)
- Embiid own mean after self-out = 0.0
- Stored `lineup-m7-v1` points row for Maxey on game `0042500214`
- Synthetic `injury_signals` row `synthetic://embiid-out-m7`

### LLM held-out (retracted)

~~From `docs/results/m7-llm.md`: N = 100, joint accuracy 1.000, bar 0.85
passed, Claude Haiku 4.5, Sonnet fallback not required.~~

That report is **invalid**. Do not cite it as LLM accuracy. Roadmap
acceptance "LLM classification accuracy on a held-out test set is
documented" is only met as a documented failure of the prior eval, not as
a passing score.

## What changed after review

**Review:** `docs/reviewer-m5-m7-m8.md` M7 B1 (feedback-fixes, A + retract).

**Required:** Stop advertising held-out Haiku joint accuracy 1.000; the
set is template-expanded, empty player predictions scored as correct, and
regex fallback can match without calling Haiku.

**Done:**
- `docs/results/m7-llm.md` rewritten as INVALID.
- Companion note on `docs/results/m7-llm-heldout.jsonl`.
- ADR-5 open question that rested on that score qualified.
- Local `docs/Roadmap.md` M7 status line retracted.
- `eval_heldout.py` no longer credits empty player names or regex-only
  rows as LLM success; unit test covers empty-pred scoring.

**Left:** No rebuilt held-out from real RSS/official items and no new
Haiku spend on this branch (explicit retract, not rebuild).

### Stale outs (I1)

**Required:** Mark each player `seen` on their newest signal before
testing out/doubtful, so available/return clears a prior out.

**Done:** `active_out_player_ids` in `lineup_apply.py` records `seen`
first; tests `test_active_out_cleared_by_later_available` and
`test_active_out_keeps_newest_out`.

**Left:** No game-date expiry for old "out tonight" claims (review I1
second bullet); still limited by `limit=500` only.

### Teammates only (I2 + light I3)

**Required:** Do not treat opposing-team outs as teammate effects; prefer
usual-starter check at inference; reduce departure / sparse-opponent
label noise in the fit.

**Done:**
- `teammate_injured_ids` + `apply_lineup_for_game` keep outs on the
  beneficiary's team and require usual-starter (or self-out).
- Fit: "out" labels require the player on tonight's team log (`appeared`);
  team timelines with fewer than 20 flagged games are skipped.
- Unit tests: `test_teammate_injured_ids_excludes_opponents`,
  `test_teammate_injured_ids_requires_usual_starter`.

**Left:** Did not regenerate `models/lineup_m7_effects.json` (still
contains older opponent / departure cells). Inference same-team filter
prevents cross-team application; a refit is a follow-up when PHI-wide
(or league) starter flags justify rewriting the artifact.

### Silent regex fallback (I7)

**Required:** Regex / rule-based classification must not arm the lineup
trigger (review example: sports-headline `\bout\b`).

**Done:** `REGEX_FALLBACK_MODEL` / `is_regex_fallback_model`; 
`active_out_player_ids` skips those `classifier_model` values after
marking `seen` (so they still clear, never arm). Test
`test_regex_fallback_out_does_not_arm_trigger`.

**Left:** Pipeline still persists regex rows for audit; classify-before
dedupe and scheduler volume (I8/I9) unchanged.

## Decisions that held

Training on `START_POSITION`, live trigger from injury signals. Minutes
proxy was not used. Scheduler jobs registered and left off.

## Not verified

- A successful live `nbainjuries` PDF parse on this machine (JVM path).
- Starter flags for non-PHI teams.
- Replacing daily `baseline-m3-v1` with injury-aware forecasts before tip.
- Production `SCHEDULER_ENABLED=true`.
