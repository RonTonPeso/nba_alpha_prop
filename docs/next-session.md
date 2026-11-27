# Next session

## Done through M10 polish (local)

M0–M8 are on `main`. M10 polish lives on `m10-polish`: short README,
architecture + model card, screenshots, UI pass, gitignored essay,
secrets grep. Provenance: `docs/provenance/m10-polish.md`.

## Do next

1. Commit / push `m10-polish` in a few clean commits (docs, then UI, or
   one polish commit if you prefer). Open PR → merge commit.
2. Run Reviewer against M10 acceptance **after** that PR is green, not
   mid-edit. Ask it to check README stranger-run, secrets, and whether
   architecture matches the code.
3. Optional M9 Discord alerts only if you want the alert path for demos.
4. Ops: confirm Railway health + Vercel `NEXT_PUBLIC_API_BASE_URL`.

## Do not

- Force-push rewritten M6–M8 history unless you explicitly want that
- Claim edge / EV in UI copy
- Turn `SCHEDULER_ENABLED` on for proofs
