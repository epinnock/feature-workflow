#!/usr/bin/env python3
"""Open follow-ups across every <features_root>/<slug>/links.json ("followups" field).

features_root comes from feature-workflow.json (current directory or a parent, or $FEATURE_WORKFLOW_CONFIG).

Usage (from anywhere):
    followups.py                      # open follow-ups, soonest trigger first
    followups.py --overdue            # only open ones whose ISO-date trigger is before today
    followups.py --all                # include done ones
    followups.py --json               # machine-readable
    followups.py --add <slug> --what "..." --trigger "YYYY-MM-DD|after X" --owner founder|orchestrator|agent [--source "file:line"]
    followups.py --done <slug> <id>   # status done, closed = today

Entry shape: {"id": "F1", "what": "...", "trigger": "YYYY-MM-DD" | "after the plugin release",
              "owner": "founder|orchestrator|agent", "status": "open|done", "source": "features/<slug>/release.md:41",
              "closed": "YYYY-MM-DD" (done only)}
Writes are atomic (temp file + os.replace), keep key order and 2-space indent. Never put secrets in "what".
"""
import argparse, datetime as dt, json, os, re, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import fwconfig  # noqa: E402

FEATURES = None  # set in main() from feature-workflow.json "features_root"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OWNERS = ("founder", "orchestrator", "agent")


def today():
    return dt.date.today().isoformat()


def manifest_path(slug):
    return os.path.join(FEATURES, slug, "links.json")


def load(slug):
    with open(manifest_path(slug), encoding="utf-8") as f:
        return json.load(f)


def save(slug, data):
    """Atomic write: temp file in the same directory, then os.replace."""
    path = manifest_path(slug)
    fd, tmp = tempfile.mkstemp(prefix=".links.", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def all_followups():
    out = []
    for slug in sorted(os.listdir(FEATURES)):
        p = manifest_path(slug)
        if not os.path.isfile(p):
            continue
        try:
            m = json.load(open(p, encoding="utf-8"))
        except json.JSONDecodeError as err:
            print(f"skip {p}: {err}", file=sys.stderr)
            continue
        for fu in m.get("followups") or []:
            out.append(dict(fu, feature=m.get("slug", slug), kind=m.get("kind", "feature")))
    return out


def sort_key(fu):
    t = str(fu.get("trigger", ""))
    return (0, t, fu.get("feature", ""), fu.get("id", "")) if ISO.match(t) else (1, t.lower(), fu.get("feature", ""), fu.get("id", ""))


def is_overdue(fu, now=None):
    t = str(fu.get("trigger", ""))
    return fu.get("status", "open") == "open" and bool(ISO.match(t)) and t < (now or today())


def next_id(fus):
    n = 0
    for fu in fus:
        m = re.match(r"^F(\d+)$", str(fu.get("id", "")))
        if m:
            n = max(n, int(m.group(1)))
    return f"F{n + 1}"


def table(rows):
    cols = ["trigger", "feature", "id", "what", "owner", "source"]
    data = [[str(r.get(c, "")) + (" (OVERDUE)" if c == "trigger" and is_overdue(r) else "")
             + (f" [done {r.get('closed', '')}]" if c == "id" and r.get("status") == "done" else "") for c in cols] for r in rows]
    width = {c: min(max([len(c)] + [len(d[i]) for d in data]), 70 if c == "what" else 48) for i, c in enumerate(cols)}

    def clip(s, w):
        return s if len(s) <= w else s[: w - 1] + "…"
    lines = ["  ".join(c.ljust(width[c]) for c in cols).rstrip(), "  ".join("-" * width[c] for c in cols)]
    for d in data:
        lines.append("  ".join(clip(v, width[c]).ljust(width[c]) for v, c in zip(d, cols)).rstrip())
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overdue", action="store_true", help="only open follow-ups with a past ISO-date trigger")
    ap.add_argument("--all", action="store_true", help="include done follow-ups")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--add", metavar="SLUG", help="append a follow-up to <features_root>/SLUG/links.json")
    ap.add_argument("--what")
    ap.add_argument("--trigger")
    ap.add_argument("--owner", choices=OWNERS)
    ap.add_argument("--source", default="")
    ap.add_argument("--done", nargs=2, metavar=("SLUG", "ID"), help="mark a follow-up done")
    a = ap.parse_args()
    global FEATURES
    FEATURES = fwconfig.load().features_root
    if not os.path.isdir(FEATURES):
        print(f"features_root {FEATURES} does not exist yet; scaffold a feature with new-feature.sh", file=sys.stderr)
        return 1

    if a.add:
        if not (a.what and a.trigger and a.owner):
            ap.error("--add needs --what, --trigger and --owner")
        if not os.path.isfile(manifest_path(a.add)):
            ap.error(f"no links.json for {a.add}")
        m = load(a.add)  # re-read right before writing: other sessions append too
        if "followups" not in m:  # keep "updated" last
            upd = m.pop("updated", None)
            m["followups"] = []
            if upd is not None:
                m["updated"] = upd
        fus = m["followups"]
        entry = {"id": next_id(fus), "what": a.what.strip(), "trigger": a.trigger.strip(), "owner": a.owner, "status": "open"}
        if a.source:
            entry["source"] = a.source.strip()
        fus.append(entry)
        m["updated"] = today()
        save(a.add, m)
        print(f"added {a.add} {entry['id']}: {entry['what']}")
        return 0

    if a.done:
        slug, fid = a.done
        if not os.path.isfile(manifest_path(slug)):
            ap.error(f"no links.json for {slug}")
        m = load(slug)
        hit = [fu for fu in m.get("followups") or [] if str(fu.get("id")) == fid]
        if not hit:
            print(f"{slug} has no follow-up {fid}", file=sys.stderr)
            return 1
        hit[0]["status"] = "done"
        hit[0]["closed"] = today()
        m["updated"] = today()
        save(slug, m)
        print(f"done {slug} {fid}: {hit[0].get('what', '')}")
        return 0

    rows = all_followups()
    if a.overdue:
        rows = [r for r in rows if is_overdue(r)]
    elif not a.all:
        rows = [r for r in rows if r.get("status", "open") == "open"]
    rows.sort(key=sort_key)
    if a.json:
        print(json.dumps([dict(r, overdue=is_overdue(r)) for r in rows], indent=2, ensure_ascii=False))
    elif not rows:
        print("no follow-ups" + (" overdue" if a.overdue else " open" if not a.all else ""))
    else:
        print(table(rows))
        n_over = sum(is_overdue(r) for r in rows)
        print(f"\n{len(rows)} follow-up(s)" + (f", {n_over} overdue" if n_over else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
