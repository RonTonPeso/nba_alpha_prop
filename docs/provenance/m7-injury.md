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

### LLM held-out

From `docs/results/m7-llm.md`:

- N = 100 frozen rows in `docs/results/m7-llm-heldout.jsonl`
- Joint accuracy (player + claim_type) = 1.000
- Bar 0.85, passed
- Model: Claude Haiku 4.5, prompt `m7-injury-v1`
- Sonnet fallback was not required

## Decisions that held

Training on `START_POSITION`, live trigger from injury signals. Minutes
proxy was not used. Scheduler jobs registered and left off.

## Not verified

- A successful live `nbainjuries` PDF parse on this machine (JVM path).
- Starter flags for non-PHI teams.
- Replacing daily `baseline-m3-v1` with injury-aware forecasts before tip.
- Production `SCHEDULER_ENABLED=true`.
