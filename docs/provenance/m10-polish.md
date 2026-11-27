# Provenance: M10 polish

## Milestone / acceptance aimed at

From `docs/Roadmap.md` § M10: Polish & Deploy:

> README has screenshots, GIF, demo link, architecture summary, model card
> link, results link
>
> No secrets in repo (audit passes)
>
> Repo can be cloned and run by a stranger following the README

Also: architecture and model card as durable interview docs; UI pass to
remove obvious scaffold tells; personal essay kept gitignored.

## What landed in this pass

- Short README with four screenshots under `docs/images/`, links to
  architecture / model card / status / results / provenance
- Full `docs/architecture.md` (already drafted; kept substantive)
- `docs/model_card.md` present
- `docs/status.md` rewritten for post-M8 / M10-in-progress
- Frontend visual pass: Source Sans 3 + IBM Plex Mono, teal accent,
  underline nav (no zinc pill chrome), solid panels instead of dashed
  AI empty boxes
- `outputFileTracingRoot` in `frontend/next.config.ts` so Next stops
  picking a parent `pnpm-lock.yaml` as the workspace root
- Gitignore entries for `portfolio-essay.md` / `docs/portfolio-essay.md`
- Personal essay written at `docs/portfolio-essay.md` (ignored)

## Decisions

**Short README, thick architecture.** Recruiters get sixty seconds; the
README is a door. The story for a technical interview lives in
`architecture.md`. Rejected stuffing the README with milestone diaries.

**Screenshots over GIF / Loom for this pass.** Static PNGs from a local
slate (`2026-06-03`) are enough to show the four views. A Loom remains
optional leverage, not a blocker for the doc surface.

**No force-rewrite of `main` history.** Fluid history for M10 means a
small number of forward commits on `m10-polish`. Rewriting already-merged
M6–M8 history would need an explicit force-push ask and would churn open
PRs.

**UI: restrained teal on warm paper, not purple/dark-glow scaffold.**
Rejected keeping default zinc + blue-700 link chrome because it reads as
generic generated dashboard. Risk: teal under dark mode needs a glance on
a real device; CSS variables cover both schemes.

**Essay gitignored.** Public repo stays portfolio-clean; the long-form
narrative is for Ronnie's prep only.

## Secrets audit (run 27 Nov 2026)

Grep for key / token / webhook patterns across the tree (excluding
`node_modules`, `.next`, locks, binary artifacts). Findings:

- No committed `.env` files; `.env` / `.env.local` stay ignored
- `docker-compose.yml` uses local default `nba` / `nba` (documented local
  only)
- `ANTHROPIC_API_KEY` read from env in injury classify; no hardcoded key
- `x-nba-stats-token: true` is an NBA stats header flag, not a secret
- Model card already tells operators to keep API keys and DB URLs out of
  git

Not run: `trufflehog` binary was not invoked in this pass.

## What would make this wrong

- Screenshots that do not match the running UI after a later redesign
  (re-capture; README paths stay the same)
- A stranger cannot boot from README because `.env.example` drifts
- A secret lands in a future commit; CI or a pre-push scan should catch it

## Verified in this pass

- `npm run build` in `frontend/` succeeded after the UI pass
- Local API on `:8000` returned Today / player detail / calibration /
  status payloads
- Screenshots written to `docs/images/{today,calibration,player,status}.png`
  from headless Chrome against `next start` on `:3000`
- Player route previously 500'd a stale chunk; fixed by clean rebuild +
  `outputFileTracingRoot`

## Not verified

- Public Railway / Vercel demo URLs staying warm (ops)
- Full GitHub Actions green on the eventual M10 PR (run after push)
- `trufflehog` scan
- GIF / Loom walkthrough
- Cloning on a cold machine with only README (local DB already warm)

## Acceptance status

Partial. Doc + screenshot + secrets-grep + local rebuild are done. Demo
link, GIF, branch protection, and CI-on-PR remain for the merge checklist.
M9 (Discord) stays intentionally out of this pass.
