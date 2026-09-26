# Stage 7 - Watch (48 hours after promotion)

"It deployed" and "it works for users" are different claims. Stage 6 proves the first; this
stage proves the second, with numbers the founder can read. It is opened as a dated follow-up
at release (owner: orchestrator) and closed here.

## What to read, per surface the feature touched

An example table; replace the "Where" column with your own tools:

| Surface | Where | What to write down |
|---|---|---|
| Web pages / API routes | your product analytics or an internal KPI page · the host's request logs for the route | requests to the new route since release, distinct users, 4xx/5xx counts |
| Services / workers | the platform's analytics for the production service · a minute of live log tail if something looks off · `/healthz` | request count, error rate, p50 latency or CPU, any new error message |
| LLM calls | your tracing tool (traces by tag / version) · your AI gateway's logs | runs since release, cost per run vs the plan's estimate, refusals/timeouts |
| Billing / credits | the usage and ledger tables | credits debited by the new task type, refunds, any hold left open |
| Errors | your error tracker for each client | new issue titles since the release sha |
| Synthetics | your scheduled checks (also on the hub, via `hub_extras`) | any check failing since release, the stage journey result |
| Store-distributed clients | store listing installs/users, error tracker | installs delta, crashes |

Read only what the feature touched; a backend-only change does not need the plugin row.
Compare against the same window before the release where a number exists.

## Verdict

Write the "Watch" section of `release.md`: date, each number read (with its source), one
verdict line ("working as released", "working, cost above estimate by x", "regression:
..."), and what was opened. Add one STATUS.md line and close the watch follow-up with
`followups.py --done <slug> <id>`.

If something is wrong: your incident log gets the entry (what users see, evidence, suspected
cause), the fix goes through Stage 6's hotfix path, and the retro line in `release.md` says
what the pipeline should have caught.
