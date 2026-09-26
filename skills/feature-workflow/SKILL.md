---
name: feature-workflow
description: The end-to-end way a new product feature gets built and shipped - Figma proposal, narrated deck, founder approval, development, security review, UAT on stage, production promotion, a 48-hour watch - with one folder per feature under the ops repo's features/ directory. Use this whenever the user asks to build, add, ship or deliver a feature or capability for any product surface (web dashboard, plugin, API, CLI, services), says "new feature", "add a page/tab/endpoint/dashboard", "let's build X", or names a stage of the pipeline ("design this first", "make the deck", "security review", "run UAT", "promote to production"). Also use it to resume a feature that is mid-pipeline. Do not use for one-line bug fixes, config changes, or pure research.
---

# Feature workflow

A feature moves through seven stages with two founder gates. The order matters because each
stage produces the input the next one needs, and because the founder decides twice: once on
the design (before any code) and once on the release (before anything reaches production).

```
1 Figma proposal ─▶ 2 Narrated deck ─▶ [Gate A: design approved]
        ─▶ 3 Development ─▶ 4 Security review ─▶ 5 UAT on stage ─▶ [Gate B: ship approved]
        ─▶ 6 Production promotion ─▶ 7 Watch (48 h)
```

**The founder does not read code.** Every stage therefore has to turn code into something
they can judge: frames and a narrated deck at Gate A; a walkthrough video, an acceptance
scorecard, a guarantees line and a Figma-vs-stage check at Gate B; a hub card in between. If a
stage's output can only be read by someone who reads code, the stage is not finished.

## Setup: the ops repo and feature-workflow.json

Everything for one feature lives in **`<features_root>/<slug>/`** inside an **ops repo** (a
repository or folder for plans, runbooks and release notes, separate from the product code)
so a later session can pick it up cold. The ops repo root holds `feature-workflow.json`, which
every script reads (found in the current directory or a parent, or at
`$FEATURE_WORKFLOW_CONFIG`). Minimal:

```json
{"features_root": "features", "github_owner": "your-org",
 "repos": [{"name": "web-dashboard", "path": "../web-dashboard", "branch": "stage",
            "test": "npm test", "typecheck": "npx tsc --noEmit", "lint": "npm run lint"}]}
```

Optional sections: `hub_artifact_url` and `hub_extras` (the hub page), `repo_health_ledger`,
`diff_service` and `dashboard` (the Figma-vs-stage check and stage screenshots), `tts` (the
walkthrough narration). The full schema is in `scripts/README.md`; a script that needs a key
you have not set stops and names it. Copy `assets/repo-health-template.md` to the ops root as
`repo-health.md` and `assets/HUB-schema.md` to `<features_root>/HUB.md` on first use.

Scripts live at `${CLAUDE_PLUGIN_ROOT}/skills/feature-workflow/scripts/` when installed as a
plugin, or at `scripts/` beside this file when the skill is copied into `~/.claude/skills/`.
Below, `scripts/...` means that directory.

```
<features_root>/<slug>/
  STATUS.md            gate log: stage, date, result, who approved, links (keep current)
  plan.md              the spec (assets/plan-template.md) - grows through every stage
  figma/               ledger.json + PNG renders of every proposal frame
  deck/                narrated-deck working dir (slides.html, narration.md, mp4, published URL)
  progress/<agent>.log one line per milestone from each delegated agent
  briefs/              the briefs sent to agents
  security-review.md   guarantees held, findings, fixes, residual risk
  uat.md               each acceptance case, result, evidence and request ids
  uat/                 walkthrough.mp4 + walkthrough.html, figma-vs-stage.md, evidence files
  release.md           what shipped (assets/release-template.md), watch results, retro
  links.json           deck, Figma, PRs, tests, acceptance, guarantees, follow-ups: feeds the hub
```

Start a feature with `scripts/new-feature.sh <slug> "<Title>"` (creates the folder from the
templates). Resume one by reading its `STATUS.md` first and continuing from the first stage
that is not marked done. Releases, evals, benchmarks and tooling that want a folder without
the pipeline are **work items**: `scripts/new-feature.sh --kind work <slug> "<Title>"`; the
hub lists them separately so the feature ledger stays a feature ledger.

**Session start.** Run `python3 scripts/followups.py` before anything else: it lists every
open follow-up across features (flags waiting to flip, held PRs, pending gates, watches),
overdue first. Act on or re-date the overdue ones; never let them live only in a STATUS line or
in memory.

Keep your copy of this skill under version control and commit every change to it with a
one-line reason. A retro finding that should change how features are built is a commit to the
skill, not a note.

## Working rules that apply to every stage

- **Delegate execution, keep judgement.** Anything executable from a precise brief (Figma
  builds, implementation, UAT runs, scripts) goes to a subagent. Every brief ends with the
  contract in `references/agent-briefs.md`, which makes the agent log milestones to
  `progress/<agent>.log`. Check status with `scripts/agent-status.sh <slug>`, never by reading
  an agent's transcript (it floods context).

- **Read the code before proposing.** Every plan section "Current behaviour" cites file:line
  from the repo, not memory. A proposal that contradicts what the code does wastes a gate.

- **The founder decides at the gates, not you.** At Gate A and Gate B stop, present, and wait.
  Autonomy inside a stage is fine; crossing a gate on your own is not, even when the answer
  seems obvious. The promotion script refuses unattended runs for the same reason.

- **The acceptance table is the contract.** `plan.md` "Acceptance tests" is complete before
  Gate A: happy, empty and denied paths, one row per guarantee, "Needs founder" marked. The
  deck shows it, UAT reports against its ids, and `scripts/acceptance-check.py <slug> --write`
  puts "passed/total, not run: ids and why" on the hub card. A case that is not in the table
  did not happen; a row missing from `uat.md` is "not run", never omitted.

- **Guarantees, in the founder's words.** `plan.md` "Guarantees" lists the three to eight
  sentences that must stay true after the feature ships ("a non-member can never read another
  project's data", "no paid task runs without a credit hold"). Each has a named negative-path
  test in Stage 3 (`guarantee-N`) and a line at the top of Stage 4's report. Gate B says
  "guarantees held n/n", not a findings table the founder has to interpret.

- **A decision budget of three.** Gate A carries at most three founder decisions: the ones
  with a price, a policy, or a high cost to reverse. Everything else is a row in the plan's
  "Defaults taken" table (default, why, cost to reverse after code) and is approved by
  silence. Decisions that are expensive to change once code exists are marked so; reversing
  who pays for something halfway through development is the kind of rework this prevents.

- **The builder never verifies.** UAT is run by a different agent from the one that built the
  PRs, briefed from `plan.md` (acceptance table, guarantees, stage URL) and not from the
  builder's report. Two independent runs are what the founder's trust rests on.

- **Numbers are deltas.** The repo-health ledger (`repo-health.md` in the ops repo) holds each
  repo's baseline (known failing files, type errors, lint state). Report
  `scripts/repo-health.sh <repo>` deltas ("tests +45, tsc ±0, no new failing files"), not the
  baseline debt again. Each feature retires one item from the debt register or says in
  STATUS.md why not.

- **Founder-hands cases are planned, not discovered.** Cases only the founder can run (a
  desktop plugin, a real third-party app install, a store publish) are marked "Needs founder"
  in the acceptance table, listed at Gate A, and either scheduled for a time they are around
  or replaced by a fixture that makes them automatable on a native UAT runner.

- **Follow-ups have a date and an owner.** Anything left dark, held or deferred goes into
  `links.json` "followups" through `scripts/followups.py --add <slug> ...` with a trigger (a
  date or an event) and an owner (founder, orchestrator, agent). The hub's "Waiting on"
  section is the ledger; STATUS lines and memory are not.

- **No-UI features still get a deck.** A feature with no screens skips the frames, not the
  deck: a three-to-five slide memo deck (what changes, guarantees, decisions, acceptance) is
  the founder's only reading surface. A plan alone is never presented at Gate A.

- **Stage is the integration branch.** PRs target `stage`; production is a fast-forward of
  `stage` to `main` through your promotion script. Before promoting, check
  `git log origin/main..origin/stage` and list every PR that would ship, not just yours.
  (Otherwise a promotion can carry someone else's freshly merged PR to production unannounced.)

- **One STATUS.md line per event.** Date, stage, result, links. Future sessions read this
  before anything else.

- **Keep links.json current.** Every agent appends what it produces (PR URL, test result with
  evidence, deck URL, release, follow-up) to `<features_root>/<slug>/links.json`, and every
  PR body includes the line `Feature: <slug> — <hub URL>` (`hub_artifact_url`). The hub page
  is rebuilt from these files (`python3 scripts/feature-hub.py`, then republish; see
  `assets/HUB-schema.md` for the schema, including `acceptance`, `guarantees`, `followups`,
  `walkthrough`, `figma_vs_stage` and `kind`).

- **Docs are a delivery item, not an afterthought.** Every plan's Delivery order ends with a
  Docs item (customer pages on your docs site, service README, operator runbook under
  `docs/runbooks/` in the ops repo). Draft them in Stage 3 with the code, show their status at
  Gate B, publish them in Stage 6.

- **Say what was not done.** If a stage is skipped or partial (a Figma-less API change, a UAT
  case that could not run), write the reason in the stage file and in STATUS.md.

## Stage 1 - Figma proposal

Goal: frames the founder can react to, in the design-system file of the surface being changed,
before any code exists. Read `references/stage-1-figma.md` for choosing the file, page and
frame conventions, transport choice (local plugin bridge vs remote Figma MCP) and the ledger
format.

Output: a page `<Feature> - proposal` in the right Figma file, `figma/ledger.json` with every
node id, PNG renders of each frame in `figma/`, and the "UI changes" and "Built Figma frames"
sections of `plan.md` filled in. Features with no UI (a pure API or worker change) skip the
frames and say so in STATUS.md; the deck in Stage 2 still happens.

## Stage 2 - Narrated deck

Goal: a 6-11 slide narrated deck that lets the founder approve the design without reading
the plan. Read `references/stage-2-deck.md`; it builds on the `narrated-deck` skill and says
which slides a feature deck needs (guarantees, acceptance table, at most three decisions) and
how to embed the Figma renders. No-UI features get the 3-5 slide memo deck described there.

Output: `deck/` with the built `index.html`, MP4 and a published link; the "Narrated deck"
section of `plan.md`; a STATUS.md line.

**Gate A - design approval.** Present: the deck link, the Figma page link, the founder
decisions (three at most, each with the recommended answer) and a pointer to the defaults
table, the acceptance table with its "Needs founder" cases and when they could run, the
feature's hub card, and a one-paragraph summary. Then stop. Record the founder's answer and
any changes they asked for in STATUS.md and `plan.md` before touching code. If they ask for
changes to the design, loop back to Stage 1 or 2 and re-present.

## Stage 3 - Development

Goal: the approved design, implemented on a `feat/<slug>` branch with tests, opened as a PR
against `stage`, deployed to the stage tier automatically. Read `references/stage-3-development.md`
for the per-repo command table (fill in your own), guarantee tests, delta reporting, what
"done" means, and the PR body shape.

Output: PR link(s), passing checks with deltas against the repo-health ledger, a
`guarantee-N` test per guarantee, the stage URL the change is live on, the feature's
walkthrough spec drafted next to its UAT spec, STATUS.md line, and the docs PR or runbook
drafted alongside the code, per the plan's **Docs** item.

## Stage 4 - Security review

Goal: the branch reviewed for the classes of defect your codebase has actually had (routes
without membership checks, trusted client-asserted identity, secrets in logs, the wrong token
type for a route), and each guarantee in the plan confirmed by test and by reading. Read
`references/stage-4-security-review.md`. Use the `security-review` skill on the branch and
write `security-review.md`: guarantees first, then findings, fixes and residual risk.
Findings that change behaviour go back through Stage 3 (new commits on the same PR).

## Stage 5 - UAT on stage

Goal: the feature exercised on the stage tier the way a user would use it, by an agent that
did not build it, with evidence the founder can watch. Read `references/stage-5-uat.md` for
the three kinds of runner (browser UAT specs in the app repo, a native desktop runner for
login-shaped flows, and the promotion smoke gates), the walkthrough video, the Figma-vs-stage
check and the acceptance scorecard. Add a UAT spec for the feature; do not only re-run the
existing ones.

Output: `uat.md` with each acceptance case, result, evidence and request ids;
`uat/walkthrough.mp4` + published `walkthrough.html`; `uat/figma-vs-stage.md` when the feature
has frames; `links.json` "acceptance" written by `scripts/acceptance-check.py`; STATUS.md line.

**Gate B - ship approval.** Present the ship card, in this order: the walkthrough video link;
acceptance passed/total with the not-run cases and why; guarantees held n/n plus any residual
risk that needs the founder's acceptance; the Figma-vs-stage summary; deviations from the
approved design; what will ship (`git log origin/main..origin/stage` with PR numbers, every
PR, not only yours); the docs status (docs PR / runbook link, or the plan's reason for
"no docs"); the follow-ups that will be opened at release, each with its trigger date and
owner; the promotion dry run; the hub card. Then stop and wait for the founder's go.

## Stage 6 - Production promotion

Goal: the tested stage commit fast-forwarded to `main`, verified live, recorded. Read
`references/stage-6-deployment.md` (it lists what your promotion script, deployment probe and
smoke gate must do). Promote with the script (never a manual push to `main`), verify
`/healthz` and the smoke gate against production, write `release.md` from
`assets/release-template.md` (shipped, verification, follow-ups, retro) and a release note in
the ops repo, open every follow-up in the ledger including the 48-hour watch, merge and
publish the docs or record why there are none, update project memory, and post the summary.

## Stage 7 - Watch

Goal: know whether the release works for real users, not only that it deployed. Read
`references/stage-7-watch.md`. Forty-eight hours after promotion, read usage, errors, spend and
synthetics for the surfaces the feature touched, write the "Watch" section of `release.md`
and one STATUS.md line, and close the watch follow-up. Anything wrong goes to your incident
log and the hotfix path in Stage 6.

## What to hand back at the end of each stage

A short message: what was produced (with links), what was verified, what was skipped and
why, and the exact next step. The founder often reads only the last message.

Before sending it, make sure `links.json` has everything the stage produced (merge in what the
agents reported if they missed it; set `stage` and `updated`), then refresh the hub:
`python3 scripts/feature-hub.py` and republish `<features_root>/hub/index.html` to the same
URL (`hub_artifact_url`). Link the hub in the message.

## What you need

- A Figma MCP server (the official remote one, or a local plugin bridge for large builds).
- The narrated-deck plugin (https://github.com/epinnock/narrated-deck) for the Gate A deck and
  the walkthrough narration (`tts.narrated_deck_dir`), with a Gemini API key.
- Playwright in the app repo for UAT specs, walkthrough recordings and stage screenshots;
  ffmpeg/ffprobe for the walkthrough video; the `gh` CLI for the hub's PR state.
- Optional: a Scry account with API access to its diff service (https://scrymore.com) for the
  automated Figma-vs-stage check; without it, compare frames by eye and write the same report.
