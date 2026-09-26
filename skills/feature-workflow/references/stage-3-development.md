# Stage 3 - Development

## Repos and commands

An example; replace the rows with your own repos and keep them in step with the `repos` list
in `feature-workflow.json` (which `repo-health.sh` reads):

| Repo | Test | Typecheck | Lint | Other |
|---|---|---|---|---|
| `<dashboard repo>` (e.g. Next.js on a preview-per-branch host) | `npm test` (unit) · component-story tests | `npx tsc --noEmit` | `npm run lint` | UAT `npm run uat`; walkthrough `npx playwright test --config=uat/playwright.walkthrough.config.ts`; a story for every new component; database rules deployed to the stage project first |
| `<plugin repo>` (e.g. a Figma plugin) | `npm test` | `npx tsc --noEmit` | `npm run lint` | a stage build pointed at the stage dashboard URL; loaded as a development plugin by hand |
| `<worker repo>` (e.g. edge workers / services) | `npm test` | `npx tsc --noEmit` | - | CI deploys to the staging environment on push to `stage`; `/healthz` carries the commit |
| `<search / API repo>` | `npm test` | `npx tsc --noEmit` | - | previews behind deployment protection; use the host's bypass mechanism for automated calls |

Write down the environment quirks your machines need (a pinned Node version on the PATH, a DNS
or proxy setting for certain providers) in this file once, so no agent rediscovers them.

## Branch, PR, stage

1. Branch `feat/<slug>` from `origin/stage` (not `main`; stage may be ahead). Before the first
   commit, list the other open PRs and `feat/*` branches in the same repo (`gh pr list --base
   stage`) and say in STATUS.md which ones touch the same files; a conflicting held PR is
   cheaper to know about on day one.
2. Implement the approved design only. Deviations from the Figma frames get a line in
   `plan.md` "Deviations" with the reason, and a note for the deck if it changes the story.
   Deviations are shown on the Gate B ship card.
3. Tests first where the behaviour is testable without a browser: API routes (auth denied,
   auth allowed, wrong role, data shape), pure functions, database rules changes. New UI
   components get a story with the states the Figma frames show.
4. **Guarantee tests.** One negative-path test per row of the plan's "Guarantees" table,
   named so the review can find it (`guarantee-1 non-member cannot read pair by id`). It
   asserts what the *other* user gets (403/404, empty, refused), not only that the happy path
   works. Fill the table's "Proved by" column with the test name and file.
5. Run the full check set, not just the new tests. Report deltas against the repo-health
   ledger with `repo-health.sh <repo>` ("tests +45, tsc ±0, no new failing files"); never
   re-list the baseline debt. Retire one item from the debt register in this PR or a small
   companion PR, or write in STATUS.md why not this time.
6. **Walkthrough spec.** Alongside the feature's UAT spec, draft
   `uat/walkthrough/<slug>.walkthrough.spec.ts` (one long test, one `step()` per acceptance
   case, step names in the founder's words; recorder and pattern in
   `scripts/walkthrough/README.md`). Stage 5 records it as the Gate B video, so write it while
   the flows are fresh.
7. Open the PR against `stage` with the body: what and why (two sentences), link to
   `plan.md` and the deck, what was tested (deltas), which guarantees have tests, what UAT will
   cover, screenshots of the built UI next to the Figma frame, and the line
   `Feature: <slug> — <hub URL>`. End with the attribution line the session requires.
8. Merge to `stage` when checks pass (or ask, if the repo has required reviewers). Stage
   deploys automatically (e.g. the `stage` branch builds the stage dashboard; workers deploy
   their staging environment from CI). Confirm the stage `/healthz` (or `/api/healthz`) shows
   the merged sha with your deployment probe (a script that prints, per service and tier, the
   sha that is actually serving).

## Access and data rules that keep coming up

- Every new API route authenticates the caller and then checks the caller's right to the data
  (project membership, org role, or a platform-level gate). "Signed in" is not "allowed".
- Client-side route guards only decide whether a page renders; a page that only some users may
  see must also hide its data behind a route that checks the claim, because the page source is
  public.
- Never trust identity asserted by the client (`X-User-Id`-style headers), even behind a shared
  key. Identity comes from a verified token or a signed caller assertion.
- A dashboard proxy that forwards to a service with the service's own bearer needs a path
  allow-list; without one it is a door into every route that service has.
- Secrets stay in the hosting platform's secret store. Know your CLI's footguns (for example,
  removing a variable from one environment can delete it from all of them).
- Database rules changes ship with the feature and are deployed to the stage project first.

## Docs, drafted with the code

The plan's Docs item is built in this stage, not after release: a docs-site PR for the
customer pages (new fields, new flows, screenshots from stage), the service README for routes,
vars and scripts, and the operator runbook (`docs/runbooks/<slug>.md` in the ops repo: how to
operate, roll back, what to watch). Link them in `links.json` under `docs`.

## Done means

PR merged to `stage`, stage healthz at that sha, the feature reachable on the stage URL, the
delta numbers in STATUS.md, a `guarantee-N` test per guarantee, the walkthrough spec drafted,
`plan.md` "Delivery" updated with the PR numbers, and the docs PR / runbook drafted (or the
plan's "no docs" reason confirmed).
