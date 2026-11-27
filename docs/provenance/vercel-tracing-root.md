# Vercel: drop outputFileTracingRoot

Written 27 Nov 2026 after production deploys of M10 polish failed.

## Where this aims

M10 acceptance (`docs/Roadmap.md`): "Demo link is live" / portfolio-ready
deploy. Visiting the Vercel production URL should serve the polished
dashboard, not stay pinned on the prior M8 build.

## Choice

Remove `outputFileTracingRoot: path.join(__dirname)` from
`frontend/next.config.ts` (and the `path` import). Leave the default
empty Next config that already deployed successfully on M8.

Rejected: keeping `outputFileTracingRoot` pinned to `__dirname` as a
"local monorepo" fix. That setting was added in `28946ec` to dodge a
parent-directory `pnpm-lock.yaml` warning on the laptop. On Vercel with
Root Directory `frontend`, the Next build completes, then the platform
post-build step fails looking for
`/vercel/path0/.next/routes-manifest-deterministic.json` (`ENOENT`,
`errorStep: buildStep`). Same failure on preview (`8b68d06`) and
production (`23b5479`) redeploys.

Rejected: forcing `--webpack` or changing Root Directory. The last READY
production deploy (`cc3007d`, M8) used default Turbopack with no tracing
root override; matching that is the smallest change.

## What would make this wrong

- The next production deploy still ends in ERROR with the same ENOENT.
  Check deployment `errorMessage` via Vercel for commit after this fix.
- Local `next build` starts resolving chunks from a wrong workspace root
  again. That would show as missing static assets or a Turbopack root
  warning when building inside `frontend/` on the laptop with a parent
  `pnpm-lock.yaml`. Fix that locally (ignore or relocate the lockfile),
  not by reintroducing this Vercel-breaking setting.

## Verified

- Production deploy `dpl_6sDvPaTXzN1TUgj2HRzTGjxgRUnk` for commit
  `fedcc85` (PR #11) reached `READY` and took the aliases including
  `nba-alpha-prop.vercel.app`. No ENOENT on
  `routes-manifest-deterministic.json`.

## Not verified yet

- Whether the live app can load comparisons from Railway once the
  frontend is READY again (separate from this packaging failure).
