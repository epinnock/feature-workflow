#!/usr/bin/env bash
# repo-health.sh <repo> [path] [--update] [--branch NAME]
#
# Runs the repo's unit tests, typecheck and lint in a checkout of <repo> and prints the delta
# against that repo's row in the repo-health ledger (default <ops root>/repo-health.md, or
# "repo_health_ledger" in feature-workflow.json; template in assets/repo-health-template.md).
#   <repo>     a "name" from the "repos" list in feature-workflow.json
#   [path]     checkout to measure; default that entry's "path"
#   --update   rewrite the repo's Baseline row (and its data line) with this run's numbers
#   --branch   label for the Branch column on --update (default: the checkout's current branch)
# Commands come from the repos entry: "test", "typecheck", "lint" (each optional), plus
# "prereq" (run once before the tests) and "env" (extra environment variables). Defaults for a
# Node repo: `npm test`, `npx --no-install tsc --noEmit` when tsconfig.json exists, `npm run lint`
# when package.json has a lint script. Counts are parsed from vitest JSON (added automatically when
# the test command runs vitest), jest or pytest summaries, and tsc / ESLint output; any other tool
# is scored by exit code.
# Exit status: 0 = no regressions; 1 = new failing test files, more failed tests, more type
# errors or more lint errors than the baseline; 2 = usage error; 3 = config error.
# Never installs, deploys or runs UAT / browser tests.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CFG() { python3 "$HERE/fwconfig.py" "$@"; }
REPO=""; WT=""; UPDATE=0; BRANCH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --update) UPDATE=1 ;;
    --branch) BRANCH="$2"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) if [ -z "$REPO" ]; then REPO="$1"; elif [ -z "$WT" ]; then WT="$1"; else echo "unexpected arg $1" >&2; exit 2; fi ;;
  esac; shift
done
[ -n "$REPO" ] || { sed -n '2,20p' "$0"; exit 2; }
OPS_ROOT=$(CFG root) || exit 3
CFG repo "$REPO" name >/dev/null || exit 3
LEDGER=$(CFG path repo_health_ledger 2>/dev/null || echo "$OPS_ROOT/repo-health.md")
if [ -z "$WT" ]; then WT=$(CFG repo "$REPO" path) || { echo "set \"path\" for $REPO in feature-workflow.json or pass [path]" >&2; exit 3; }; fi
[ -d "$WT" ] || { echo "no checkout at $WT" >&2; exit 2; }
WT=$(cd "$WT" && pwd)
repo_field() { CFG repo "$REPO" "$1" 2>/dev/null || true; }
TEST_CMD=$(repo_field test); TSC_CMD=$(repo_field typecheck); LINT_CMD=$(repo_field lint); PREREQ_CMD=$(repo_field prereq)
# extra env from the repos entry ("env": {"NAME": "value"})
ENV_JSON=$(repo_field env)
if [ -n "$ENV_JSON" ]; then
  while IFS= read -r line; do [ -n "$line" ] && export "$line"; done < <(python3 -c 'import json,sys; [print(f"{k}={v}") for k,v in json.loads(sys.argv[1]).items()]' "$ENV_JSON")
fi
export CI=1 FORCE_COLOR=0 NO_COLOR=1 NEXT_TELEMETRY_DISABLED=1

OUT=$(mktemp -d "${TMPDIR:-/tmp}/repo-health.XXXXXX")
trap 'rm -rf "$OUT"' EXIT
START=$(date +%s)
cd "$WT"

has_npm_script() { [ -f package.json ] && node -e "process.exit((require('./package.json').scripts||{})[process.argv[1]]?0:1)" "$1" 2>/dev/null; }
if [ -z "$TEST_CMD" ] && has_npm_script test; then TEST_CMD="npm test"; fi
if [ -z "$TSC_CMD" ] && [ -f tsconfig.json ]; then TSC_CMD="npx --no-install tsc --noEmit --pretty false"; fi
if [ -z "$LINT_CMD" ] && has_npm_script lint; then LINT_CMD="npm run lint"; fi

echo "[repo-health] $REPO @ $WT ($(git rev-parse --short HEAD 2>/dev/null))" >&2
# 0. prerequisite the tests need on a fresh checkout (e.g. a build step CI runs first)
if [ -n "$PREREQ_CMD" ]; then
  echo "[repo-health] prereq: $PREREQ_CMD" >&2
  timeout -k 10 300 bash -c "$PREREQ_CMD" </dev/null >"$OUT/prereq.log" 2>&1
fi
# 1. unit tests (vitest gets a JSON report and is forced out of watch mode)
if [ -n "$TEST_CMD" ]; then
  runs_vitest=0
  case "$TEST_CMD" in *vitest*) runs_vitest=1 ;; "npm test"|"npm run test"|"pnpm test"|"yarn test")
    [ -f package.json ] && node -p "(require('./package.json').scripts||{}).test||''" | grep -q vitest && runs_vitest=1 ;; esac
  extra=""
  if [ $runs_vitest = 1 ]; then
    sep=""; case "$TEST_CMD" in npm*|"pnpm test"|"yarn test") sep="-- " ;; esac
    watch=""; case "$TEST_CMD" in *"vitest run"*) ;; *) watch="--run " ;; esac
    [ -f package.json ] && node -p "(require('./package.json').scripts||{}).test||''" | grep -q "vitest run" && watch=""
    extra=" ${sep}${watch}--reporter=default --reporter=json --outputFile.json=$OUT/vitest.json"
  fi
  echo "[repo-health] tests: $TEST_CMD$extra" >&2
  timeout -k 10 900 bash -c "$TEST_CMD$extra" </dev/null >"$OUT/test.log" 2>&1; echo $? >"$OUT/test.rc"
else echo none >"$OUT/test.rc"; fi
# 2. typecheck
if [ -n "$TSC_CMD" ]; then
  echo "[repo-health] typecheck: $TSC_CMD" >&2
  timeout -k 10 480 bash -c "$TSC_CMD" </dev/null >"$OUT/tsc.log" 2>&1; echo $? >"$OUT/tsc.rc"
else echo none >"$OUT/tsc.rc"; fi
# 3. lint
if [ -n "$LINT_CMD" ]; then
  echo "[repo-health] lint: $LINT_CMD" >&2
  timeout -k 10 300 bash -c "$LINT_CMD" </dev/null >"$OUT/lint.log" 2>&1; echo $? >"$OUT/lint.rc"
else echo none >"$OUT/lint.rc"; fi
echo $(( $(date +%s) - START )) >"$OUT/secs"

python3 - "$REPO" "$WT" "$OUT" "$LEDGER" "$UPDATE" "$BRANCH" <<'PY'
import json, os, re, subprocess, sys, datetime, fcntl, collections
repo, wt, out, ledger, update, branch = sys.argv[1:7]
update = update == "1"
rd = lambda n: open(os.path.join(out, n), errors="replace").read() if os.path.exists(os.path.join(out, n)) else ""
git = lambda *a: subprocess.run(["git", "-C", wt, *a], capture_output=True, text=True).stdout.strip()
m = {"repo": repo, "sha": git("rev-parse", "--short", "HEAD"),
     "branch": branch or git("rev-parse", "--abbrev-ref", "HEAD"),
     "date": datetime.date.today().isoformat(), "secs": int(rd("secs") or 0)}
dirty = git("status", "--porcelain", "--untracked-files=no")
if dirty: m["dirty"] = True

# tests
rc = rd("test.rc").strip(); log = rd("test.log")
t = {"status": "ok", "passed": 0, "failed": 0, "skipped": 0, "failing_files": []}
vj = os.path.join(out, "vitest.json")
if rc == "none":
    t["status"] = "no test script"
elif os.path.exists(vj):
    j = json.load(open(vj))
    t["passed"] = j.get("numPassedTests", 0); t["failed"] = j.get("numFailedTests", 0)
    t["skipped"] = j.get("numPendingTests", 0) + j.get("numTodoTests", 0)
    for r in j.get("testResults", []):
        if r.get("status") == "failed":
            t["failing_files"].append(os.path.relpath(r["name"], wt))
    # a file that errors on import may have no assertions; count it as a failure
    if not j.get("success", True) and not t["failing_files"] and rc not in ("0",):
        t["status"] = "error"
else:
    # no vitest JSON: try jest and pytest summaries, else score by exit code
    jm = re.search(r"^Tests:\s+(.*?)(\d+) total", log, re.M)
    pm = re.findall(r"(\d+) (passed|failed|skipped|errors?)\b", "\n".join(l for l in log.splitlines() if l.startswith("=")))
    if jm:
        for n, k in re.findall(r"(\d+) (passed|failed|skipped|todo)", jm.group(1)):
            key = {"passed": "passed", "failed": "failed"}.get(k, "skipped")
            t[key] += int(n)
        t["counted"] = "jest summary"
    elif pm:
        for n, k in pm:
            key = "passed" if k == "passed" else "skipped" if k == "skipped" else "failed"
            t[key] += int(n)
        t["counted"] = "pytest summary"
    elif rc == "0":
        t["counted"] = "exit code"
    elif rc not in ("124", "137"):
        t["failed"] = 1
        t["counted"] = "exit code"
        tail = [l for l in log.strip().splitlines() if l.strip()][-6:]
        t["error"] = " / ".join(x.strip() for x in tail)[:400]
    else:
        t["status"] = "timeout"
if rc in ("124", "137"): t["status"] = "timeout"
if t["status"] in ("error", "timeout"):
    tail = [l for l in log.strip().splitlines() if l.strip()][-6:]
    t["error"] = " / ".join(x.strip() for x in tail)[:400]
t["failing_files"].sort()
m["tests"] = t

# tsc
tlog = rd("tsc.log"); trc = rd("tsc.rc").strip()
errs = re.findall(r"^(.+?)\(\d+,\d+\): error TS\d+", tlog, re.M)          # tsc
errs += re.findall(r"^(.+?):\d+(?::\d+)?: error:", tlog, re.M)                   # mypy
glob = len(re.findall(r"^error TS\d+", tlog, re.M))
files = collections.Counter(os.path.normpath(e) for e in errs)
if trc == "none":
    m["tsc"] = {"errors": 0, "files": {}, "status": "not configured"}
else:
    m["tsc"] = {"errors": len(errs) + glob, "files": dict(files.most_common()),
                "status": "timeout" if trc in ("124", "137") else ("ok" if trc == "0" or errs or glob else "error")}
if m["tsc"]["status"] == "error": m["tsc"]["error"] = " / ".join(tlog.strip().splitlines()[-4:])[:400]

# lint
lrc = rd("lint.rc").strip(); llog = rd("lint.log")
L = {"status": "unconfigured", "errors": 0, "warnings": 0}
if lrc != "none":
    mm = re.search(r"(\d+) problems? \((\d+) errors?, (\d+) warnings?\)", llog)
    if re.search(r"How would you like to configure ESLint|couldn't find (a|an eslint\.config|the config)|No ESLint configuration", llog, re.I):
        L["status"] = "unconfigured"
    elif lrc in ("124", "137"):
        L["status"] = "timeout"
    elif mm:
        L.update(status="errors" if int(mm.group(2)) else "clean", errors=int(mm.group(2)), warnings=int(mm.group(3)))
    elif re.search(r"^\S.*\n?\d+:\d+\s+Error:", llog, re.M) or re.search(r"\s+Error: ", llog):
        L.update(status="errors", errors=len(re.findall(r"\d+:\d+\s+Error: ", llog)),
                 warnings=len(re.findall(r"\d+:\d+\s+Warning: ", llog)))
        if L["errors"] == 0: L["status"] = "broken"
    elif lrc == "0":
        L["warnings"] = len(re.findall(r"\d+:\d+\s+Warning: ", llog))
        L["status"] = "clean"
    else:
        L["status"] = "broken"
    if L["status"] in ("broken", "timeout"):
        L["error"] = " / ".join(x.strip() for x in llog.strip().splitlines()[-4:] if x.strip())[:300]
m["lint"] = L

def fmt_tests(t):
    if t["status"] in ("error", "timeout", "no test script"):
        return f"could not run ({t['status']})"
    if t.get("counted") == "exit code":
        return "fail (exit code)" if t["failed"] else "pass (exit code)"
    return f"{t['passed']} pass / {t['failed']} fail / {t['skipped']} skip"
def fmt_lint(L):
    if L["status"] == "errors": return f"{L['errors']} errors" + (f", {L['warnings']} warn" if L["warnings"] else "")
    if L["status"] == "clean": return "clean" + (f" ({L['warnings']} warn)" if L["warnings"] else "")
    return L["status"]
def fmt_tsc(x):
    if x["status"] == "not configured": return "not configured"
    if x["status"] != "ok": return f"could not run ({x['status']})"
    return str(x["errors"])
def row(m):
    ff = "<br>".join(f"`{f}`" for f in m["tests"]["failing_files"]) or "-"
    top = ", ".join(f"`{f}` {n}" for f, n in list(m["tsc"]["files"].items())[:5])
    tsc = fmt_tsc(m["tsc"]) + (f" ({top})" if top else "")
    sha = m["sha"] + (" (dirty)" if m.get("dirty") else "")
    return f"| {m['repo']} | {m['branch']} | {sha} | {m['date']} | {fmt_tests(m['tests'])} | {ff} | {tsc} | {fmt_lint(m['lint'])} | {m['secs']//60}m{m['secs']%60:02d}s |"

# baseline lookup
base = None
if os.path.exists(ledger):
    for line in open(ledger):
        mm = re.match(r"<!-- repo-health:data (\{.*\}) -->", line.strip())
        if mm:
            d = json.loads(mm.group(1))
            if d["repo"] == repo: base = d

print(f"\nrepo-health {repo} @ {m['sha']}{' (dirty tree)' if m.get('dirty') else ''} ({m['branch']}), {m['secs']}s")
bad = []
if base is None:
    print("  no baseline row for this repo in", ledger)
else:
    bt, ct = base["tests"], m["tests"]
    def d(a, b): return f"{b - a:+d}"
    print(f"  baseline: {base['sha']} ({base['branch']}, {base['date']})\n")
    print(f"  {'metric':<16}{'baseline':>16}{'now':>16}{'delta':>8}")
    for k in ("passed", "failed", "skipped"):
        print(f"  {'tests ' + k:<16}{bt.get(k,0):>16}{ct.get(k,0):>16}{d(bt.get(k,0), ct.get(k,0)):>8}")
    bs, cs = base["tsc"]["errors"], m["tsc"]["errors"]
    print(f"  {'type errors':<16}{bs:>16}{cs:>16}{d(bs, cs):>8}")
    bl, cl = base["lint"], m["lint"]
    print(f"  {'lint':<16}{fmt_lint(bl):>16}{fmt_lint(cl):>16}{d(bl['errors'], cl['errors']):>8}")
    if ct["status"] != "ok" and bt["status"] == "ok":
        bad.append(f"tests could not run: {ct['status']}: {ct.get('error','')}")
    new_ff = sorted(set(ct["failing_files"]) - set(bt["failing_files"]))
    fixed_ff = sorted(set(bt["failing_files"]) - set(ct["failing_files"]))
    if new_ff: bad.append("new failing test files: " + ", ".join(new_ff))
    if ct["failed"] > bt["failed"]: bad.append(f"failed tests up {ct['failed'] - bt['failed']}")
    if cs > bs: bad.append(f"type errors up {cs - bs}")
    if m["tsc"]["status"] != "ok" and base["tsc"]["status"] == "ok": bad.append(f"typecheck could not run: {m['tsc'].get('error','')}")
    new_tf = sorted(f for f in m["tsc"]["files"] if m["tsc"]["files"][f] > base["tsc"]["files"].get(f, 0))
    if new_tf: print("\n  files with more type errors: " + ", ".join(new_tf))
    if cl["errors"] > bl["errors"]: bad.append(f"lint errors up {cl['errors'] - bl['errors']}")
    if cl["status"] != bl["status"]: print(f"  lint status changed: {bl['status']} -> {cl['status']}")
    if fixed_ff: print("  test files now passing: " + ", ".join(fixed_ff))
    if ct["failing_files"]: print("  failing test files: " + ", ".join(ct["failing_files"]))
    print()
    print("  REGRESSION: " + "; ".join(bad) if bad else "  no regressions vs baseline")
for part, x in (("tests", m["tests"]), ("tsc", m["tsc"]), ("lint", m["lint"])):
    if x.get("error"): print(f"  {part} could not run cleanly: {x['error']}")

if update:
    if not os.path.exists(ledger): sys.exit(f"ledger missing: {ledger}")
    with open(ledger + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        lines = open(ledger).read().splitlines()
        data = f"<!-- repo-health:data {json.dumps(m, sort_keys=True)} -->"
        r = row(m)
        i_row = next((i for i, l in enumerate(lines) if l.startswith(f"| {repo} |")), None)
        if i_row is not None: lines[i_row] = r
        else:
            hdr = next(i for i, l in enumerate(lines) if l.startswith("| Repo |"))
            end = hdr + 2
            while end < len(lines) and lines[end].startswith("|"): end += 1
            lines.insert(end, r)
        i_d = next((i for i, l in enumerate(lines) if l.startswith(f'<!-- repo-health:data {{') and json.loads(l[len("<!-- repo-health:data "):-4])["repo"] == repo), None)
        if i_d is not None: lines[i_d] = data
        else:
            anchor = next(i for i, l in enumerate(lines) if l.strip() == "<!-- repo-health:data-end -->")
            lines.insert(anchor, data)
        open(ledger, "w").write("\n".join(lines) + "\n")
    print(f"  updated {repo} row in {ledger}")
sys.exit(1 if bad else 0)
PY
