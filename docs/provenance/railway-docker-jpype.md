# Railway Docker: jpype / nbainjuries build

Written 27 Nov 2026 after Railway failed to build the image from
`Merge pull request #7` (m7-injury).

## Where this aims

Restore a deployable backend image on Railway after M7 added
`nbainjuries` → `jpype1`.

## Choice

Use `python:3.12-slim` and install `g++` plus `default-jre-headless`
before `uv sync`.

Rejected: staying on `python:3.14-slim` and only adding g++. 3.14 is
newer than the local toolchain and more likely to force source builds.
Rejected: dropping `nbainjuries` from the lockfile in this fix. The
package is part of M7; the image should still install it.

## What would make this wrong

- `uv sync` still fails on Railway (missing header package, or Java
  path). The next build log is the check.
- Image builds but official injury PDF parse fails at runtime for JVM
  reasons. That is a separate ops note; RSS still works.

## Not verified yet

- A green Railway deploy after this push (will show on the next build).
