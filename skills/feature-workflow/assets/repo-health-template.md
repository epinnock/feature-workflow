# Repo health ledger

Copy this file to the root of your ops repo as `repo-health.md` (or set `repo_health_ledger` in
`feature-workflow.json`). It holds the baseline of unit tests, typecheck and lint for each repo
in `repos`, measured on the integration branch (e.g. `stage`) in a clean worktree with a fresh
install. Feature reports state deltas against this table instead of repeating the known debt.

## How to use

- In STATUS.md, report checks as deltas against the row below, e.g. "tests +12/-0, tsc ±0,
  lint ±0 vs repo-health baseline 1a2b3c4", not the absolute debt.
- `repo-health.sh <repo> [path]` runs the same checks in a checkout (default the repo's `path`
  in `feature-workflow.json`) and prints the delta table: tests ±, type errors ±, new failing
  test files, lint. It exits 1 when new failing files, more failed tests, more type errors or
  more lint errors appear.
- Each feature retires one item from the Debt register. After the retirement merges, run
  `repo-health.sh <repo> --update --branch stage` on an up-to-date stage checkout to rewrite
  that repo's row, and strike the item below with the PR number.
- The script never installs, deploys or runs UAT / browser tests; install dependencies first
  if the lockfile moved.
- First run: `repo-health.sh <repo> --update --branch stage` adds the row and its data line.

## Baseline

| Repo | Branch | SHA | Date | Tests (pass / fail / skip) | Failing test files | tsc errors (top files) | Lint | Run time |
|---|---|---|---|---|---|---|---|---|

## Debt register

One item per known problem, each with the date it was first seen and what retires it. Examples
of the kind of item that belongs here:

- **H1** web-dashboard: lint unconfigured (no `lint` script, no ESLint config). First seen YYYY-MM-DD.
  Retire: add an ESLint flat config and a `lint` script, wire it into CI.
- **H2** api-worker: CI never runs the unit tests or the typecheck before deploying. First seen YYYY-MM-DD.
  Retire: add `npm test` and `npm run typecheck` steps ahead of the staging deploy job.
- **H3** api-worker: `npm test` fails on a fresh checkout until a build step has run. First seen YYYY-MM-DD.
  Retire: add a `pretest` script (or a vitest globalSetup) that runs the build.
- **H4** web-dashboard: `npm test` is watch-mode `vitest`, so a bare `npm test` hangs outside CI. First seen YYYY-MM-DD.
  Retire: make `test` = `vitest run` and keep `test:watch` for watch mode.
- **H5** both `package-lock.json` and `pnpm-lock.yaml` are tracked; CI installs from only one. First seen YYYY-MM-DD.
  Retire: delete the unused lockfile and set `packageManager` in package.json.

## Machine-readable rows (used by repo-health.sh; do not edit by hand)

<!-- repo-health:data-end -->
