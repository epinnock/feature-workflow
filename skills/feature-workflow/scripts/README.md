# feature-workflow scripts

Everything the skill runs lives here. Python scripts are stdlib only (python3.9+), the shell
scripts are bash, `capture-stage.mjs` is Node 18+ with Playwright from your app checkout.
Every script reads one config file, `feature-workflow.json`, at the root of your **ops repo**
(the repository or folder that holds `features/`, the repo-health ledger and your runbooks).

| Script | What it does |
|---|---|
| `new-feature.sh [--kind feature\|work] <slug> "<Title>"` | Scaffolds `<features_root>/<slug>/` from `../assets/` (plan, STATUS, figma/, deck/, progress/, briefs/, links.json). `--kind work` makes a work-item folder (STATUS, progress/, links.json only). |
| `agent-status.sh [slug] [n]` | Last `n` lines of every delegated agent's `progress/<agent>.log`, with its state and age. |
| `acceptance-check.py <slug> [--write]` | Maps every acceptance id in `plan.md` to its row in `uat.md`; prints PASS / FAIL / partial / not run with reasons; `--write` stores the summary in `links.json` "acceptance". |
| `followups.py` | Lists open follow-ups across all features (overdue first); `--add`, `--done`, `--overdue`, `--all`, `--json`. |
| `feature-hub.py [--offline]` | Renders every `links.json` into one self-contained HTML page (`<features_root>/hub/index.html`) with live PR state and CI from `gh`. |
| `repo-health.sh <repo> [path] [--update]` | Runs a repo's tests, typecheck and lint and prints the delta against its baseline row in the repo-health ledger. |
| `capture-stage.mjs` | Full-page screenshot of one stage page in a given signed-in state, at a Figma frame's width. |
| `figma-vs-stage.py` | Sends each approved Figma frame and its stage screenshot to Scry's diff service and writes `uat/figma-vs-stage.md`. |
| `walkthrough/build-walkthrough.py` | Turns a recorded Playwright walkthrough plus a narration file into a captioned, narrated MP4 and an HTML page (Gate B's video). |
| `walkthrough/walk.ts` | The step recorder the walkthrough spec uses; copy it into your app repo. |
| `fwconfig.py` | The config reader the others use; also a small CLI (`fwconfig.py get <key>`). |

## feature-workflow.json

Found in the current directory or any parent, or at `$FEATURE_WORKFLOW_CONFIG`. The directory
holding it is the **ops root**: relative paths in the config and in every `links.json` resolve
against it. A script that needs a key you have not set stops with a message naming the key.
Credentials are never in this file: it names the **environment variables** that hold them.

```json
{
  "features_root": "features",
  "github_owner": "your-org",
  "hub_artifact_url": "https://link-where-you-publish-the-hub",
  "hub_title": "Feature hub",
  "hub_safe_email_domains": ["example.org"],
  "hub_extras": [
    {"title": "Synthetic checks", "command": "python3 tools/synthetics-card.py", "timeout": 60}
  ],
  "repo_health_ledger": "repo-health.md",
  "repos": [
    {"name": "web-dashboard", "path": "../web-dashboard", "branch": "stage", "github": "your-org/web-dashboard",
     "test": "npm test", "typecheck": "npx --no-install tsc --noEmit --pretty false", "lint": "npm run lint"},
    {"name": "api-worker", "path": "../api-worker", "branch": "stage",
     "test": "npm test", "prereq": "npm run build:assets", "env": {"NODE_OPTIONS": "--max-old-space-size=4096"}}
  ],
  "diff_service": {
    "base_url": "https://your-stage-diff-service.example.org",
    "stage_env": "staging",
    "token_env": "DIFF_STAGE_TOKEN",
    "project_id": "your-stage-project-id",
    "wallet": "your-billing-wallet-id",
    "bucket": "your-stage-screenshot-bucket",
    "credits_per_unit": 1,
    "pair_id_prefix": "",
    "s3": {
      "endpoint": "https://your-account.r2.cloudflarestorage.com",
      "region": "auto",
      "access_key_env": "DIFF_S3_ACCESS_KEY_ID",
      "secret_key_env": "DIFF_S3_SECRET_ACCESS_KEY"
    }
  },
  "dashboard": {
    "stage_url": "https://stage.your-product.example.org",
    "repo": "../web-dashboard",
    "stage_host_pattern": "^https://(stage\\.your-product\\.example\\.org|[a-z0-9-]+\\.preview\\.example\\.org)$",
    "viewer_link_template": "{stage_url}/projects/{project_id}?diffLink={link_id}",
    "issue_link_template": "{stage_url}/projects/{project_id}?issue={issue}",
    "login_path": "/login",
    "auth": {
      "mode": "storage-state",
      "storage_state": "../web-dashboard/uat/.auth/stage-user.json",
      "service_account": "secrets/stage-service-account.json",
      "env_file": ".env.stage.local",
      "default_uid": "stage-uat-user-uid"
    }
  },
  "tts": {"narrated_deck_dir": "~/.claude/skills/narrated-deck"}
}
```

| Key | Used by | Meaning |
|---|---|---|
| `features_root` | all | Folder of feature folders, relative to the ops root. Default `features`. |
| `github_owner` | feature-hub | Owner for bare repo names in `links.json` `prs[].repo`. |
| `repos[].github` | feature-hub | Explicit `owner/name` for one repo (overrides `github_owner`). |
| `hub_artifact_url` | feature-hub, SKILL | Where the hub page is published; shown in the footer and put in PR bodies. Optional. |
| `hub_title`, `hub_safe_email_domains` | feature-hub | Page title; email domains left unredacted in evidence excerpts (all others become `[email]`). |
| `hub_extras` | feature-hub | Optional hook: commands run from the ops root whose stdout (an HTML `<section class="feat">…</section>` fragment) is placed above the cards, e.g. your synthetic checks. Skipped with `--offline`. Output is not redacted, so print no secrets. |
| `repo_health_ledger` | repo-health | Ledger path. Default `<ops root>/repo-health.md` (template: `../assets/repo-health-template.md`). |
| `repos[].name`, `.path`, `.branch` | repo-health | Repo key, checkout path, integration branch. |
| `repos[].test`, `.typecheck`, `.lint` | repo-health | Commands. Defaults for a Node repo: `npm test`; `tsc --noEmit` if `tsconfig.json` exists; `npm run lint` if the script exists. |
| `repos[].prereq`, `.env` | repo-health | A command run before the tests (a build step CI runs first); extra environment variables. |
| `diff_service.base_url`, `.stage_env` | figma-vs-stage | Stage diff service; the script refuses one whose `/healthz` `env` is not `stage_env` (default `staging`). |
| `diff_service.token_env` | figma-vs-stage | Name of the env var holding the bearer token (or `<NAME>_FILE` pointing at a file). |
| `diff_service.project_id`, `.wallet` | figma-vs-stage | Project the pairs are registered under; billing wallet for the runs (optional if your account has a default). |
| `diff_service.bucket`, `.s3.*` | figma-vs-stage | Bucket the diff service reads screenshots from, its S3 endpoint and region, and the names of the env vars holding the access key id and secret. |
| `diff_service.credits_per_unit`, `.pair_id_prefix` | figma-vs-stage | How many credits one price unit costs (for the report), and a prefix your account's pair ids need. |
| `dashboard.stage_url`, `.repo` | capture-stage, figma-vs-stage | Stage dashboard URL; a checkout with Playwright installed. |
| `dashboard.stage_host_pattern` | capture-stage | Regex the base URL must match; default the `stage_url` host, localhost, 127.0.0.1. Production is refused. |
| `dashboard.viewer_link_template`, `.issue_link_template` | figma-vs-stage | Links from the report into your viewer; placeholders `{stage_url}` `{project_id}` `{link_id}` `{pair_id}` `{issue}`. |
| `dashboard.auth.*` | capture-stage | How screenshots are signed in: `storage-state` (a Playwright storageState file; works with any auth), `firebase-custom-token` (service account + env file with `NEXT_PUBLIC_FIREBASE_*`), or `none`. |
| `tts.narrated_deck_dir` | build-walkthrough | Where the narrated-deck skill is installed (its `assets/tts.py` voices the walkthrough). |

## new-feature.sh, agent-status.sh, followups.py, acceptance-check.py

```bash
S=${CLAUDE_PLUGIN_ROOT}/skills/feature-workflow/scripts      # or wherever you copied the skill
$S/new-feature.sh order-history "Order history"
$S/new-feature.sh --kind work q3-release "Q3 release"
$S/agent-status.sh order-history
python3 $S/followups.py                      # open follow-ups, soonest first
python3 $S/followups.py --add order-history --what "flip ORDERS_V2 on in production" \
    --trigger 2026-10-03 --owner founder --source "features/order-history/release.md:12"
python3 $S/followups.py --done order-history F1
python3 $S/acceptance-check.py order-history --write
```

`acceptance-check.py` reads the first table under `## Acceptance tests` in `plan.md` (column 1
id, column 2 case, an optional "Needs founder" column) and every table in `uat.md` that has an
"Acceptance #" (or "#") column and a "Result" column. Bullets under a "Not exercised" / "Not
run" heading that cite "#8" or "case 8" give the reason an id was not run. It refuses `--write`
when `uat.md` has no table keyed by acceptance id, because the counts would understate coverage.

## feature-hub.py

```bash
python3 $S/feature-hub.py            # PR state and head-commit CI from `gh api`, plus hub_extras
python3 $S/feature-hub.py --offline  # links.json only
```

Writes `<features_root>/hub/index.html`, a stable path: republish that file to the same page
to keep its URL. Small text evidence files (`.md/.log/.txt/.json` under 60 KB) linked from
`tests[].evidence` are embedded as collapsible excerpts after secret redaction (private keys,
common token prefixes, bearer headers, `token=`/`secret=`/`password=`/`api_key=` values) and
email redaction (all domains except `hub_safe_email_domains`). The `links.json` schema is in
`../assets/HUB-schema.md`.

## repo-health.sh

```bash
$S/repo-health.sh web-dashboard                       # delta vs the ledger row, exit 1 on regression
$S/repo-health.sh web-dashboard /tmp/wt-feature       # measure another checkout
$S/repo-health.sh web-dashboard --update --branch stage   # rewrite the baseline row
```

Counts come from vitest's JSON report (added automatically when the test command runs
vitest), jest or pytest summaries, and `tsc` / mypy / ESLint output; any other tool is scored
by exit code. It exits 1 when there are new failing test files, more failed tests, more type
errors or more lint errors than the baseline. It never installs, deploys or runs browser tests.

## figma-vs-stage.py: Gate B "Figma vs stage"

Requires a Scry account with API access to its diff service, and a bucket the diff service can
read (see the top-level README). It compares the approved proposal frames
(`<feature>/figma/ledger.json` + PNGs) with screenshots of the built feature on stage and writes
`<feature>/uat/figma-vs-stage.md`: one verdict per frame ("matches what you approved" /
"differs here"), the findings in words, and viewer links when the templates are set. It also
sets `links.json` `"figma_vs_stage": {path, summary}` (atomic, re-read before write).

### 1. Screenshot stage in the frame's state

One PNG per frame, named after the frame (`Orders / List · loaded` → `orders-list-loaded.png`),
at the frame's width, full page, in the same state as the frame (same role, same
empty/loaded/error state):

```bash
C=$S/capture-stage.mjs
D=features/order-history/uat/figma-vs-stage-shots
node $C --path /orders --out $D/orders-list-loaded.png --height 1104 --wait-testid orders-table
node $C --path /orders --out $D/orders-access-denied.png --storage-state ../web-dashboard/uat/.auth/viewer.json
```

`--signed-out`, `--uid`, `--storage-state`, `--wait-selector`, `--wait-text`, `--settle ms`
and `--viewport-only` are available. It grows the viewport until an inner `<main>` scroller no
longer scrolls (plain `fullPage` stops at the viewport in app shells). Stage data is live: a
frame drawn with fixed numbers will always "differ" on the numbers.

### 2. Run the check

```bash
python3 $S/figma-vs-stage.py --slug order-history \
  --shots features/order-history/uat/figma-vs-stage-shots [--map map.json] [--tier basic] [--dry-run]
```

- `--map` JSON `{ "<frame name>": "<png path>" }` for shots named differently, or
  `{ "<frame name>": "skip: <reason>" }` for a state stage cannot show. Every frame without a
  shot is listed under "Not compared" with its reason; none is skipped silently.
- `--dry-run` matches frames and prepares the images without uploading or spending, and needs
  no credentials.

Per frame (stage only; it exits unless `/healthz` reports `env == diff_service.stage_env`):
1. Screenshot scaled to the frame's width if it differs (Pillow if installed, else ffmpeg);
   both images kept in `<feature>/uat/figma-vs-stage/`.
2. Both PNGs PUT into `diff_service.bucket` at
   `<project>/figma-vs-stage/<slug>/<frame>-{figma,stage}-<sha8>.png` (S3 API, SigV4).
3. `POST /api/pairs` `{pair_id, project_id, link_id: fvs-<slug>-<frame>, name, image_a_key (Figma), image_b_key (stage)}`
   (Plus tier also sends `figma_file_key` + `figma_node_id` from the ledger).
4. `POST /api/agent/annotate?async=1` `{pair_id, who: "figma-vs-stage", trigger: "run", tier, billing_wallet}`
   → 202 `run_id`; polls `GET /api/agent/runs/<run_id>` every 8 s until terminal.
5. `GET /api/issues?pair=<pair_id>` for this run's findings, and the run's hybrid report
   (saved beside the images).

Credentials: the env vars named by `diff_service.token_env`, `diff_service.s3.access_key_env`
and `diff_service.s3.secret_key_env` (each may instead be `<NAME>_FILE` pointing at a file).
Neither is printed or written anywhere.

### Reading the result

Blocking = the judge's suggested blocker/major; minor = minor/nit. The suggestion is not
calibrated for this use: on data-driven pages it rates live numbers, other users' avatars and
changes approved after the proposal as blockers. Before Gate B, read each finding against the
two images and mark it **real drift**, **later approved change**, or **capture artefact**
(viewport, scroll, live data, signed-in identity). The judge may call image B "Storybook"; here
it is the stage page. Each frame's findings also appear in the project's triage list in the
diff service; a re-run re-registers the same pair.
