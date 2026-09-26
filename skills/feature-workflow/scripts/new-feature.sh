#!/usr/bin/env bash
# Scaffold <features_root>/<slug>/ from the feature-workflow templates.
# Usage: new-feature.sh [--kind feature|work] <slug> "<Title>"   (slug: lowercase, digits, dashes)
#   feature (default): plan.md, STATUS.md, figma/, deck/, progress/, briefs/, links.json ("kind": "feature")
#   work: a work item (release, eval, research, tooling) - STATUS.md, progress/, links.json ("kind": "work") only
# features_root comes from feature-workflow.json (found in the current directory or a parent,
# or at $FEATURE_WORKFLOW_CONFIG).
set -euo pipefail
USAGE="usage: $0 [--kind feature|work] <slug> \"<Title>\""
KIND=feature
if [[ "${1:-}" == "--kind" ]]; then KIND="${2:-}"; shift 2 || true; fi
[[ "$KIND" == feature || "$KIND" == work ]] || { echo "$USAGE" >&2; exit 2; }
SLUG="${1:-}"; TITLE="${2:-}"
[[ "$SLUG" =~ ^[a-z0-9][a-z0-9-]{1,60}$ && -n "$TITLE" ]] || { echo "$USAGE" >&2; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
ASSETS="$(cd "$HERE/../assets" && pwd)"
FEATURES="$(python3 "$HERE/fwconfig.py" features-root)"
DIR="$FEATURES/$SLUG"
[[ -e "$DIR" ]] && { echo "exists: $DIR (resume it by reading STATUS.md)" >&2; exit 1; }
DATE="$(date -u +%Y-%m-%d)"
# Escape sed replacement metacharacters in the title (/, &, \).
TITLE_SED=$(printf '%s' "$TITLE" | sed -e 's/[\/&\\]/\\&/g')
render() { sed -e "s/{{TITLE}}/$TITLE_SED/g" -e "s/{{SLUG}}/$SLUG/g" -e "s/{{DATE}}/$DATE/g" "$ASSETS/$1" > "$2"; }
if [[ "$KIND" == work ]]; then
  mkdir -p "$DIR/progress"
  render STATUS-work-template.md "$DIR/STATUS.md"
  STAGE="work item - in progress"
else
  mkdir -p "$DIR/figma" "$DIR/deck" "$DIR/progress" "$DIR/briefs"
  for t in plan STATUS; do render "$t-template.md" "$DIR/$t.md"; done
  STAGE="1 figma - in progress"
fi
python3 - "$DIR/links.json" "$SLUG" "$TITLE" "$KIND" "$STAGE" "$DATE" <<'PY'
import json, sys
path, slug, title, kind, stage, date = sys.argv[1:7]
m = {"slug": slug, "title": title, "kind": kind, "stage": stage, "deck": {}, "figma": [], "prs": [],
     "tests": [], "releases": [], "docs": [], "followups": [], "updated": date}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(m, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
echo "$DIR"
ls -1 "$DIR"
