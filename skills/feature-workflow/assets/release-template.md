# {{TITLE}} - release {{DATE}}

**Service(s):** … · **Production:** main `<sha>` (prev `<sha>`), deploy `<id>`, promoted `<HH:MM>` UTC
by your promotion script after Gate B (founder, {{DATE}}). Row in the deploy ledger; release index updated.

**PRs shipped (stage → main, everything in the range):** #… · #… (name anything that was not
this feature's).

**Production state after the release:** flags and modes as they are now (what is dark, what is
shadow, what is on).

**Verification:** production `/healthz` sha, smoke script result, the first real request
(run id / request id), D1 migration tail if any.

**UAT + review:** `uat.md` (acceptance passed/total, not run: …), `uat/walkthrough.html`
(artifact URL), `uat/figma-vs-stage.md` (summary line), `security-review.md` (guarantees held
n/n, residual risks accepted by the founder at Gate B: …).

**Docs:** docs-site page(s) live (URL), README, runbook; or the plan's "no docs" reason.

## Follow-ups (opened in the ledger with `followups.py --add`)

| Id | What | Trigger (date or event) | Owner |
|---|---|---|---|
| F1 | 48-hour watch (Stage 7) | {{DATE}} + 2 days | orchestrator |

## Watch (filled in Stage 7)

Date, what was read (usage, errors, spend, synthetics) with the numbers, verdict, anything
opened in your incident log.

## Retro (three lines)

- What the pipeline got wrong or slow on this feature:
- What to change in the skill (committed as: `<sha>` or "nothing"):
- What to keep doing:
