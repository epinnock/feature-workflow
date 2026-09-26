# feature-workflow

A Claude Code skill that takes a product feature from a Figma proposal to a watched production
release in seven stages with two founder gates. Its premise: **the founder does not read
code**, so every stage has to produce something they can judge without it: frames and a
narrated deck before any code is written; a narrated walkthrough video, an acceptance
scorecard, a "guarantees held n/n" line and a Figma-vs-stage check before anything ships; and
one hub page that shows every feature's state in between. Agents do the building; the founder
decides twice.

```
1 Figma proposal ─▶ 2 Narrated deck ─▶ [Gate A: design approved]
        ─▶ 3 Development ─▶ 4 Security review ─▶ 5 UAT on stage ─▶ [Gate B: ship approved]
        ─▶ 6 Production promotion ─▶ 7 Watch (48 h)
```

## The two gates

**Gate A - design approval** (before any code). The founder sees: the narrated deck (6-11
slides, 4-5 minutes; a 3-5 slide memo deck for features with no UI), the Figma proposal page,
at most three decisions (each with a recommended answer and whether it is expensive to reverse
after code), a pointer to the defaults taken by silence, the acceptance table with the cases
only the founder can run, and the feature's hub card.

**Gate B - ship approval** (before production). The founder sees the ship card, in order: the
walkthrough video of the feature running on stage; acceptance passed/total with the not-run
cases and why; guarantees held n/n and any residual risk that needs their acceptance; the
Figma-vs-stage summary; deviations from the approved design; every PR that will ship; docs
status; the follow-ups that will be opened, each with a date and an owner; the promotion dry
run; the hub card.

## Working rules

- **The acceptance table is the contract.** Complete before Gate A (happy, empty and denied
  paths, one row per guarantee, "Needs founder" marked); UAT reports against its ids; a case
  not in `uat.md` is "not run", never omitted.
- **Guarantees in the founder's words.** Three to eight sentences that must stay true after
  release, each with a named negative-path test (`guarantee-N`) and a line at the top of the
  security review.
- **A decision budget of three** at Gate A; everything else is a default approved by silence.
- **The builder never verifies.** UAT is run by a different agent, briefed from the plan, not
  from the builder's report.
- **Numbers are deltas** against a repo-health ledger (tests ±, type errors ±, new failing
  files), never the baseline debt again; each feature retires one debt item.
- **Follow-ups have a date and an owner**, in a ledger the hub shows; not in prose.
- **No-UI features still get a deck** (a memo deck); a plan alone is never presented.
- **The founder decides at the gates**; agents never cross one on their own.
- **Stage is the integration branch**; production is a fast-forward of the tested stage sha.
- **Stage 7 watch**: 48 hours after release, read usage, errors, spend and synthetics and
  write a verdict.
- **Retro in three lines**, and a finding that should change the pipeline is a commit to the
  skill.

## Layout

```
.claude-plugin/plugin.json, marketplace.json
skills/feature-workflow/
  SKILL.md                     the pipeline, the working rules, the gates
  references/                  stage-1-figma … stage-7-watch, agent-briefs (the brief contract)
  assets/                      plan, STATUS, STATUS-work, release templates;
                               repo-health-template.md (the ledger); HUB-schema.md (links.json)
  scripts/                     the tools below; scripts/README.md documents each and the config
```

Each feature gets a folder in your ops repo:

```
<features_root>/<slug>/
  STATUS.md  plan.md  figma/  deck/  progress/<agent>.log  briefs/
  security-review.md  uat.md  uat/  release.md  links.json
```

## Scripts

| Script | What it does |
|---|---|
| `new-feature.sh` | Scaffolds a feature (or `--kind work` item) folder from the templates. |
| `agent-status.sh` | Latest milestone lines from every delegated agent's progress log. |
| `acceptance-check.py` | Scores `uat.md` against the plan's acceptance table; `--write` puts it on the hub card. |
| `followups.py` | Lists, adds and closes dated follow-ups across all features, overdue first. |
| `feature-hub.py` | Renders every `links.json` into one HTML hub with live PR and CI state from `gh`; secret-redacted evidence excerpts; optional `hub_extras` hook. |
| `repo-health.sh` | Runs a repo's tests, typecheck and lint and prints deltas against its ledger row; exits 1 on regression. |
| `capture-stage.mjs` | Full-page screenshot of a stage page in a given signed-in state, at a Figma frame's width. |
| `figma-vs-stage.py` | Sends each approved frame and its stage screenshot to Scry's diff service and writes a per-frame verdict report. |
| `walkthrough/build-walkthrough.py` | Narrated, captioned MP4 + HTML page from a recorded Playwright walkthrough (`walkthrough/walk.ts` is the step recorder). |

Python scripts are stdlib only; shell scripts are bash; the `.mjs` runs on Node 18+.

## Install

In Claude Code:

```
/plugin marketplace add epinnock/feature-workflow
/plugin install feature-workflow@feature-workflow
```

Then ask for a feature: "let's build an order history page", or invoke `/feature-workflow`.

Without the plugin system, copy the skill folder into your skills directory:

```bash
cp -r skills/feature-workflow ~/.claude/skills/
```

## Configure

Create `feature-workflow.json` at the root of your ops repo (the repo or folder that holds
`features/`, the repo-health ledger and your runbooks). Minimal:

```json
{
  "features_root": "features",
  "github_owner": "your-org",
  "repos": [
    {"name": "web-dashboard", "path": "../web-dashboard", "branch": "stage",
     "test": "npm test", "typecheck": "npx tsc --noEmit", "lint": "npm run lint"}
  ]
}
```

Add `hub_artifact_url`, `hub_extras`, `diff_service`, `dashboard` and `tts` as you adopt the
hub, the Figma-vs-stage check and the walkthrough; the full schema is in
`skills/feature-workflow/scripts/README.md`. Scripts find the file in the current directory or
a parent (or at `$FEATURE_WORKFLOW_CONFIG`) and stop with a message naming any key they need
and you have not set. Credentials are never in the file; it names the environment variables
that hold them. Then copy `assets/repo-health-template.md` to `repo-health.md` and
`assets/HUB-schema.md` to `features/HUB.md`, and fill in the tables in
`references/stage-1-figma.md` (which Figma file per surface) and
`references/stage-3-development.md` (commands per repo).

## What you need

- A Figma MCP server: the official remote one for small proposals, or a local plugin bridge
  for large builds.
- The narrated-deck plugin (https://github.com/epinnock/narrated-deck) for the Gate A deck and
  the walkthrough narration, with a Gemini API key.
- Playwright in your app repo for UAT specs, walkthrough recordings and stage screenshots.
- ffmpeg and ffprobe for the walkthrough video; the `gh` CLI for the hub's PR state.
- A stage tier that deploys from a `stage` branch, and a promotion script that fast-forwards
  `main` after health and smoke gates (Stage 6 lists what it must do).
- Optional: a Scry account with API access to its diff service (https://scrymore.com) for the
  automated Figma-vs-stage check. Without it, compare frames by eye and write the same report.

This is the pipeline used to build Scry.

## License

MIT
