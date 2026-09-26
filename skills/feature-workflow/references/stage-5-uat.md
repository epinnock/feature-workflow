# Stage 5 - UAT on stage

UAT is run by an agent that did not build the feature, briefed from `plan.md` (acceptance
table, guarantees, stage URL, the UAT account) and not from the builder's report or PRs. The
brief says which runner each acceptance row uses; the agent's job is to make every row PASS,
FAIL or "not run: why", and to leave evidence the founder can watch.

## Runners

Three kinds of runner, each for a different shape of check. Pick by the acceptance row; most
web features need the first and, if they touch sign-in or a desktop app, the second.

### 1. Browser UAT (Playwright specs in the app repo)

Specs in `uat/tests/NN-<area>.spec.ts`; a global setup signs in without driving the sign-in UI
(mint a session from a stage service account, or load a saved storageState). Against the stage
URL:

```bash
cd <dashboard repo>
UAT_BASE_URL=<stage url> npm run uat -- uat/tests/01-auth.spec.ts uat/tests/NN-<feature>.spec.ts --workers=1
```

Write a new spec for the feature: the happy path, the empty state, and the denied path
(a user who must not see it). Data assertions should compare against the source of truth
(a database count read with an admin client), not against the UI's own number.

### 2. Native desktop UAT

For flows that need a real browser session or another app: sign-in forms, an OAuth or
device-code approval, a desktop plugin, anything with a popup. Run them on a machine with a
logged-in GUI session (a spare desktop reachable over SSH works well), each run with a request
id and an output directory, and only count a run where every required case passed. Check the
server-side evidence (the audit row, the token record) from the orchestrator's machine, not
from the runner's own report. Gotchas worth writing down for your setup: keychain or
credential-store items created from an SSH session may be unreadable from the GUI session (and
vice versa); screen locks and sleep settings kill long runs; use a dedicated browser profile.

### 3. Smoke gates

Your promotion script should run each service's smoke check against staging before it will
push to production. If the feature adds a route that production must answer, extend that
service's smoke check so the gate covers it from now on, and run it by hand first against the
stage URL.

### Cases only the founder can run

They were marked "Needs founder" at Gate A. Do not mark them not-run and move on: either the
founder runs them at the time agreed at Gate A (write the outcome and their words in
`uat.md`), or a fixture now makes them automatable (record which). A feature promoted with a
founder-hands case still open carries it as a dated follow-up on the ship card.

## The walkthrough video (Gate B's deck)

Record the feature's walkthrough spec on stage and narrate it, so the founder approves the
release by watching two to three minutes, the way they approved the design:

```bash
cd <dashboard repo>   # same environment as the browser UAT above
npx playwright test --config=uat/playwright.walkthrough.config.ts uat/walkthrough/<slug>.walkthrough.spec.ts
python3 <skill>/scripts/walkthrough/build-walkthrough.py \
  --video <run>/video.webm --steps <report>/steps.json \
  --narration <features_root>/<slug>/uat/narration.md \
  --out <features_root>/<slug>/uat/walkthrough.mp4 --title "<Feature> on stage, <date>"
```

One step per acceptance case, step names in the founder's words, narration 30-60 words per
step saying what they are seeing and which acceptance row it proves. Publish
`uat/walkthrough.html` and put both in `links.json` "walkthrough". Recipe and options:
`scripts/walkthrough/README.md`.

## Figma vs stage

For every proposal frame, screenshot the built screen on stage at the frame's width and in
the frame's state (`capture-stage.mjs`), then run a visual diff judge on the pair. The script
here uses Scry's diff service (needs a Scry account with API access; see the README):

```bash
python3 <skill>/scripts/figma-vs-stage.py --slug <slug> --shots <features_root>/<slug>/uat/figma-vs-stage-shots/
```

It writes `uat/figma-vs-stage.md` (per frame: verdict, issues in words, viewer link) and the
summary into `links.json` "figma_vs_stage". Read the issues before quoting them: dynamic data,
scroll position and viewport differences are capture artefacts, real drift is a deviation the
founder has to see on the ship card. Frames with no stage screenshot are listed as "not
compared", never dropped. Cost: one run per frame at the chosen tier. Without a diff service,
do the same comparison by eye, frame by frame, and write the same file by hand.

## Scoring

```bash
python3 <skill>/scripts/acceptance-check.py <slug> --write
```

It maps every acceptance id in `plan.md` to its row in `uat.md` and writes
`links.json` "acceptance" (passed/total, not run with reasons, founder-hands ids). Run it after
every UAT pass; the hub card and the ship card read from it.

## Evidence

`uat.md`:

```
# UAT - <feature> - <date>
Stage commit: <sha> (healthz verified) · Runner agent: <name> (did not build the PRs)
| Acceptance # | Case | Runner | Result | Evidence |
| 1 | happy path | playwright NN-orders | PASS | report path / screenshot |
| 4 | denied for non-member | playwright NN-orders | PASS | 403 body |
| ... |
Not run: <acceptance #> - <why> (and when it will run, if it will)
Walkthrough: uat/walkthrough.mp4 (<m:ss>, URL)
Figma vs stage: uat/figma-vs-stage.md (<summary line>)
```

PASS means the case ran on stage at the sha that will be promoted and the evidence is on
disk. A case that could not run is listed, not omitted. Re-run after any Stage 3 fix, and
re-record the walkthrough if a fix changed what the founder would see.
