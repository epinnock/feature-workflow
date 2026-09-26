# Feature hub and the links.json schema

Copy this file to `<features_root>/HUB.md` in your ops repo and fill in where the hub is
published. Each feature folder carries one `links.json`; `feature-hub.py` renders all of them
into one page with every feature's deck, Figma pages, PRs (live state + CI), tests, acceptance
coverage, follow-ups and releases.

- **Published at:** <hub URL; also `hub_artifact_url` in `feature-workflow.json`>
- **Source of truth:** `<features_root>/<slug>/links.json`, one per feature folder
- **Generator:** `feature-hub.py` → `<features_root>/hub/index.html` (stable path, so republishing keeps the URL)

## Regenerate

```
python3 <skill>/scripts/feature-hub.py            # add --offline to skip the gh api calls and hub_extras
```
Then republish the same file (`<features_root>/hub/index.html`) to the same URL.

## links.json schema

```json
{
  "slug": "order-history",
  "title": "Order history",
  "stage": {"current": "6 released", "gate_a": "approved 2026-09-22", "gate_b": "approved 2026-09-23"},
  "deck": {"url": "https://<where the deck is published>", "mp4": "features/<slug>/deck/<slug>.mp4"},
  "figma": [{"label": "Dashboard DS · <Feature> - proposal (12:345)", "url": "https://www.figma.com/design/…"}],
  "prs": [{"repo": "web-dashboard", "number": 107, "url": "https://github.com/<owner>/web-dashboard/pull/107", "role": "PR 1 …"}],
  "tests": [{"label": "…", "kind": "unit|ci|e2e|uat|native-uat|smoke", "result": "pass|fail|partial|blocked",
             "date": "YYYY-MM-DD", "evidence": "path or URL", "summary": "one line with the real numbers"}],
  "releases": [{"label": "…", "date": "YYYY-MM-DD", "path_or_url": "features/<slug>/release.md", "commit": "abc1234"}],
  "docs": [{"label": "Plan", "path_or_url": "features/<slug>/plan.md"}],
  "kind": "feature",
  "acceptance": {"total": 22, "passed": 20, "not_run": [{"id": "8", "case": "…", "why": "…"}],
                 "partial": [], "failed": [], "founder_hands": ["12"], "source": "features/<slug>/uat.md", "checked": "YYYY-MM-DD"},
  "guarantees": {"held": 6, "total": 6, "source": "features/<slug>/security-review.md"},
  "followups": [{"id": "F1", "what": "…", "trigger": "YYYY-MM-DD | after the plugin release",
                 "owner": "founder|orchestrator|agent", "status": "open|done", "source": "features/<slug>/release.md:41",
                 "closed": "YYYY-MM-DD (done only)"}],
  "walkthrough": {"mp4": "features/<slug>/uat/walkthrough.mp4", "url": "https://<where the walkthrough is published>"},
  "figma_vs_stage": {"path": "features/<slug>/uat/figma-vs-stage.md", "summary": "5 frames, 0 blocking diffs"},
  "updated": "YYYY-MM-DD"
}
```

Optional fields (all may be omitted):
- `kind`: `"feature"` (default) or `"work"`. Work items (releases, evals, research, tooling folders with no plan.md)
  render in a collapsed "Work items" section after the features and are left out of the feature/PR/test counts.
  Scaffold one with `new-feature.sh --kind work <slug> "<Title>"`.
- `acceptance`: written by `acceptance-check.py <slug> --write` (plan.md
  "## Acceptance tests" vs uat.md results keyed by an "Acceptance #" / "#" column). The card shows
  "Acceptance passed/total" with the not-run and partial ids, their reasons and a "needs founder" marker.
- `guarantees`: how many of the security review's guarantees held; the card shows "Guarantees held n/m".
- `followups`: open items with a date or a condition. Every open one across all folders appears in the
  "Waiting on" table at the top (ISO dates ascending, then condition triggers; past dates highlighted as overdue)
  and in the header counts. Manage them with `followups.py` (list, `--overdue`, `--all`, `--json`,
  `--add <slug> --what … --trigger … --owner …`, `--done <slug> <id>`); it writes atomically.
- `walkthrough`, `figma_vs_stage`: UAT walkthrough video/artifact and the Figma-vs-stage comparison, linked on the card.
Local paths are relative to the ops root (the directory holding `feature-workflow.json`) unless absolute. The page shows them as text (they are not
reachable from the web); small text evidence (.md/.log/.txt/.json under 60 KB) is embedded as a collapsible,
secret-redacted excerpt. PR state and head CI are fetched from GitHub at generation time, so only numbers go in
links.json. Never put tokens or secret values in links.json.

## Keeping it current

Every agent appends what it produces (PR, test result with evidence, deck URL, release) to its
feature's links.json, and every PR body carries `Feature: <slug> — <hub URL>`
(references/agent-briefs.md).
