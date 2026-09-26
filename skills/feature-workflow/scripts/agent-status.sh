#!/usr/bin/env bash
# Show the latest progress of every delegated agent in a feature (or all features).
# Usage: agent-status.sh [slug] [lines-per-agent=3]
# Reads <features_root>/<slug>/progress/*.log; features_root comes from feature-workflow.json.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(python3 "$HERE/fwconfig.py" features-root)" || exit 3
N="${2:-3}"
shopt -s nullglob
found=0
for dir in "$ROOT"/${1:-*}/progress; do
  slug=$(basename "$(dirname "$dir")")
  for log in "$dir"/*.log; do
    found=1
    last=$(tail -n1 "$log"); state=$(cut -d'|' -f2 <<<"$last" | xargs)
    mtime=$(stat -c %Y "$log" 2>/dev/null || stat -f %m "$log")
    age=$(( ( $(date +%s) - mtime ) / 60 ))
    printf '== %s / %s  [%s, updated %s min ago]\n' "$slug" "$(basename "$log" .log)" "${state:-?}" "$age"
    tail -n "$N" "$log" | sed 's/^/   /'
  done
done
[[ $found == 1 ]] || echo "no progress logs under $ROOT/${1:-*}/progress/"
