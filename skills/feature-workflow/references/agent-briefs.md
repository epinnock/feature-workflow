# Briefing and tracking delegated agents

Executable work (Figma builds, implementation, UAT runs, scripts, docs) goes to subagents:
your strongest coding model by default, a parallel coding agent for large implementation
fan-outs. The orchestrator plans, briefs, verifies and decides gates. Append the contract below
to every brief, filling in `<features_root>`, `<slug>`, `<agent>` (a short kebab name, e.g.
`orders-view`, `stage-uat`), `<skill>` (where the skill's scripts are) and `<hub URL>`.

**The builder never verifies.** The Stage 5 UAT agent is a different agent from the one(s)
that built the PRs. Its brief contains `plan.md` (acceptance table, guarantees, the stage URL,
the UAT account and runner recipe) and nothing from the builder: no PR links, no builder
report, no "what I tested". If the verifier cannot find how to exercise a case from the plan
alone, that is a finding about the plan, and it goes in `uat.md` as "not run: <why>".

**Brief the founder's words, not the code's.** Step names in walkthrough specs, acceptance
cases and narration are written as the founder would say them ("a viewer cannot run a diff"),
because those strings end up on the ship card and in the video.

## Why progress files

An agent's transcript is the only other window into it, and it is raw JSONL of every tool call
and file dump; reading it floods the orchestrator's context. A one-line-per-milestone log is
cheap to read, survives a session restart, and leaves an audit trail in the feature folder.
Check all agents of a feature with `agent-status.sh <slug>`.

## Contract (paste at the end of every brief)

```
## Progress reporting (required)
- Append one line per milestone to <features_root>/<slug>/progress/<agent>.log
  (create the directory if missing). Format: `<UTC HH:MM> | <stage> | <one sentence>`, e.g.
  `10:42 | build | Orders list + filters done, 12 unit tests pass`.
  Write it with: `mkdir -p <dir> && printf '%s | %s | %s\n' "$(date -u +%H:%M)" build "…" >> <file>`
- Stages to use, in order as they apply: start, investigate, build, test, pr, ci, merge, deploy,
  uat, done, blocked. Log at least: start (with the plan in one sentence), each stage change,
  every failure you are retrying (with the error in a few words), and a final `done` or
  `blocked` line that matches your final report.
- If you receive a message asking for status, reply in at most three lines, then continue.
- Never write secrets, tokens or personal data to the log.
- Append what you produce to <features_root>/<slug>/links.json (schema in HUB-schema.md):
  each PR under `prs`, each test run under `tests` (kind, result, date, evidence path or URL,
  one-line summary with real numbers), a deck under `deck`, a release under `releases`, a
  walkthrough under `walkthrough`; bump `updated`. Re-read the file right before writing and
  write atomically (other agents append too). Keep the JSON valid and never add secrets.
  Anything you leave dark, held or deferred:
  `python3 <skill>/scripts/followups.py --add <slug> --what "..." --trigger <date|event> --owner agent`.
- Every PR body includes the line `Feature: <slug> — <hub URL>`.

## Working rules
- Work in your own git worktree/branch off `origin/stage`; never modify a main checkout.
- No production deploys or pushes to `main`; PRs target `stage` unless the brief says otherwise.
- Save CI minutes: open PRs as drafts (`gh pr create --draft`) while iterating if CI skips
  drafts; run the repo's checks locally; batch commits and push once per working session, not
  after every edit; `gh pr ready` once it is done, which starts the one CI run that gates merge.
- Verify with the repo's own commands and report deltas against the repo-health ledger
  (`<skill>/scripts/repo-health.sh <repo>`): tests ±, tsc ±, new failing files. Do not re-list
  the baseline debt.
- Commit trailer and PR footer: the attribution lines the session requires.
- Final report: what was done (links, shas), verification numbers, deviations and why, what is
  left, anything that failed with exact error text. Keep it under ~60 lines.
```
