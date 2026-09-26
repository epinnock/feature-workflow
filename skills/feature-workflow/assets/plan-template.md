# {{TITLE}}

Status: Proposed · Started {{DATE}} · Folder `features/{{SLUG}}/`

## Summary

Two or three sentences: who needs this, what changes for them, what is deliberately not
included. Written for the founder, not for the code.

## Current behaviour (from code)

What the product does today, each claim with `repo/path/file.ts:line`. Include the data
model as it exists (collections, fields, who writes them) and the access rules that apply.

## Target behaviour

### User-facing

Screen by screen, state by state. Copy in quotes as it will ship.

### Data and API

| Endpoint / job | Method | Auth | Reads | Writes | Notes |
|---|---|---|---|---|---|

Data model changes (new collections/fields, indexes, rules).

### Access

Who can see it, which gate proves it (project role, org role, platform claim), what everyone
else gets (404 vs 403 vs hidden nav).

### Not in v1

## Guarantees

Three to eight sentences that must stay true once this ships, in the founder's words. Each
gets a negative-path test named `guarantee-N` in Stage 3 and a line at the top of the
security review. Example: "G1 A signed-in user who is not a member of a project can never read
that project's diffs, even with the pair id."

| # | Guarantee | Proved by (test name, Stage 3) |
|---|---|---|
| G1 | | |

## UI changes

One paragraph per screen or state, matching the Figma frame names.

## Delivery order

Numbered PRs in merge order, each with the repo, what it contains, and what can be verified
on stage after it lands. The last item is always **Docs**: which pages on your customer docs
site change or are added, which README / runbook in the service repo changes, and, for an
operator-only feature, the runbook in the ops repo (`docs/runbooks/`). "No docs" must say why
(nothing customer-visible and nothing an operator has to run).

## Docs

Customer-facing: page(s) on your docs site and the API/object fields they must list.
Operator-facing: README sections, runbook (`docs/runbooks/<slug>.md` in the ops repo), what to
watch after release. Filled in Stage 3 (drafted with the code) and checked at Gate B.

## Acceptance tests

Complete before Gate A: the happy path, the empty state, the denied path, one row per
guarantee, and every case only the founder can run marked in "Needs founder" (with when it
could happen). UAT reports against these ids; `acceptance-check.py` scores them.

| # | Case | Guarantee | Runner | Expected | Needs founder |
|---|---|---|---|---|---|
| 1 | | | playwright / native-uat / smoke / curl / unit | | no |

## Founder decisions (three at most)

Only decisions with a price, a policy, or a high cost to reverse. Each with the recommended
answer and why, phrased so "yes" is a decision. Mark the ones that are expensive to change
once code exists.

| # | Decision | Recommended | Why | Expensive to reverse after code? |
|---|---|---|---|---|
| D1 | | | | |

## Defaults taken

Everything else decided by us, approved by silence at Gate A. The founder can veto any row.

| Decision | Default | Why | Cost to reverse after code |
|---|---|---|---|

## References

Files, prior plans, memory notes, external docs.

## Built Figma frames

Filled in Stage 1: file, page id, title card, table of frame -> node id, local pieces,
deviations from the shipped components and why.

## Narrated deck

Filled in Stage 2: path, slide count, duration, voice, artifact URL, MP4.

## Deviations during development

Filled in Stage 3 when the build departs from the approved frames, with the reason. Shown on
the Gate B ship card.
