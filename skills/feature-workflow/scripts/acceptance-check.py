#!/usr/bin/env python3
"""Acceptance coverage for one feature (features_root from feature-workflow.json): plan.md "## Acceptance tests" vs uat.md results.

Usage:
    acceptance-check.py <slug>           # print per-id status and a summary
    acceptance-check.py <slug> --write   # also store the summary in features/<slug>/links.json "acceptance"

Plan: the first markdown table under "## Acceptance tests"; column 1 = id, column 2 = case. An optional
column headed "Needs founder" (any non-empty value other than -/no) marks ids that need the founder's hands.
UAT: every table in uat.md with a column headed "Acceptance #", "Acceptance" or "#" and a "Result" column.
Cells like "11", "14 (flip)", "5, 20" map to ids; "-", "rule 3 amendment", "Stage 4" are ignored. Bullets under
a "Not exercised" / "Not done" heading (or a "Not exercised ...:" line) that cite "#8", "case 8" or
"acceptance test 8" give the reason an id was not run.
Status per id: PASS | FAIL | partial | not run. Exit 1 when plan.md, its section, or uat.md is missing.
"""
import argparse, datetime as dt, json, os, re, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import fwconfig  # noqa: E402

CFG = None
FEATURES = None
UNMAPPED = "no UAT result row cites this id"
KEYWORDS = [("not run", "not run"), ("not exercised", "not run"), ("not done", "not run"), ("pass", "PASS"),
            ("fail", "FAIL"), ("partial", "partial"), ("blocked", "blocked"), ("skipped", "not run")]


def clean(s):
    s = re.sub(r"\*\*|__|`", "", s or "")
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def short(s, n=180):
    s = clean(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells = re.split(r"(?<!\\)\|", line)
    return [c.replace("\\|", "|").strip() for c in cells]


def tables(lines, lo=0, hi=None):
    """Yield (header_cells, [(lineno, cells), ...]) for each markdown table in lines[lo:hi]."""
    hi = len(lines) if hi is None else hi
    i = lo
    while i < hi:
        if lines[i].lstrip().startswith("|") and i + 1 < hi and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            head = split_row(lines[i])
            rows, j = [], i + 2
            while j < hi and lines[j].lstrip().startswith("|"):
                rows.append((j + 1, split_row(lines[j])))
                j += 1
            yield head, rows
            i = j
        else:
            i += 1


def section(lines, title_rx):
    for i, l in enumerate(lines):
        if re.match(title_rx, l):
            level = len(l) - len(l.lstrip("#"))
            for j in range(i + 1, len(lines)):
                m = re.match(r"^(#+)\s", lines[j])
                if m and len(m.group(1)) <= level:
                    return i + 1, j
            return i + 1, len(lines)
    return None


def parse_plan(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    sec = section(lines, r"^##\s+Acceptance tests\b")
    if not sec:
        return None, "no '## Acceptance tests' section in plan.md"
    for head, rows in tables(lines, *sec):
        hl = [clean(h).lower() for h in head]
        fcol = next((k for k, h in enumerate(hl) if "founder" in h), None)
        items = []
        for ln, cells in rows:
            if len(cells) < 2 or not clean(cells[0]):
                continue
            fid = clean(cells[0]).lstrip("#").strip()
            founder = fcol is not None and fcol < len(cells) and clean(cells[fcol]).lower() not in ("", "-", "–", "no", "n")
            items.append({"id": fid, "case": clean(cells[1]), "founder": founder, "line": ln})
        if items:
            return items, None
    return None, "the '## Acceptance tests' section has no table"


def result_of(text):
    t = clean(text).lower()
    best = None
    for kw, st in KEYWORDS:
        k = t.find(kw)
        if k != -1 and (best is None or k < best[0]):
            best = (k, st)
    return best[1] if best else None


def ids_in_cell(cell, known):
    c = clean(cell)
    if not re.match(r"^#?[A-Z]?\d", c):
        return [], ""
    qual = " ".join(re.findall(r"\(([^)]*)\)", c))
    base = re.sub(r"\([^)]*\)", "", c)
    return [x for x in re.findall(r"[A-Z]?\d+[a-z]?", base) if x in known], qual


def parse_uat(path, known):
    lines = open(path, encoding="utf-8").read().splitlines()
    rows_by_id = {}
    n_tables = 0
    for head, rows in tables(lines):
        hl = [clean(h).lower() for h in head]
        acol = next((k for k, h in enumerate(hl) if h in ("acceptance #", "acceptance", "#", "acceptance test", "acc #")), None)
        rcol = next((k for k, h in enumerate(hl) if "result" in h), None)
        if acol is None or rcol is None:
            continue
        n_tables += 1
        for ln, cells in rows:
            if max(acol, rcol) >= len(cells):
                continue
            ids, qual = ids_in_cell(cells[acol], known)
            st = result_of(cells[rcol]) or "unknown"
            for fid in ids:
                rows_by_id.setdefault(fid, []).append({"status": st, "qual": qual, "text": cells[rcol], "line": ln})
    # "Not exercised" / "Not done" bullets
    notes = {}
    in_sec = False
    for ln, l in enumerate(lines, 1):
        h = re.match(r"^(#+)\s+(.*)", l)
        if h:
            in_sec = bool(re.search(r"not (exercised|done|run)", h.group(2), re.I))
            continue
        inline = re.match(r"^\s*(?:[-*]\s*)?\**not (?:exercised|done|run)\b[^:]*:\**\s*(.*)", l, re.I)
        if in_sec and re.match(r"^\s*[-*]\s", l) or inline:
            text = inline.group(1) if inline else re.sub(r"^\s*[-*]\s+", "", l)
            cited = set()
            for rx in (r"#(\d+[a-z]?)\b", r"(?i)acceptance(?: test)?s?\s+(\d+[a-z]?)\b", r"(?i)\bcase\s+(\d+[a-z]?)\b", r"(?i)\btest\s+(\d+[a-z]?)\b"):
                cited.update(x for x in re.findall(rx, clean(text)) if x in known)
            for fid in cited:
                notes.setdefault(fid, []).append({"text": text, "line": ln})
    return rows_by_id, notes, n_tables


def classify(item, rows, notes):
    fid = item["id"]
    rs = rows.get(fid, [])
    ns = notes.get(fid, [])
    sts = [r["status"] for r in rs]
    why = ""
    if "FAIL" in sts:
        st = "FAIL"
        why = short(next(r["text"] for r in rs if r["status"] == "FAIL"))
    elif "partial" in sts:
        st = "partial"
        why = short(next(r["text"] for r in rs if r["status"] == "partial"))
    elif "PASS" in sts:
        partish = any(re.search(r"half|part", r["qual"], re.I) for r in rs if r["status"] == "PASS")
        if ns and partish:
            st, why = "partial", short(ns[0]["text"])
        else:
            st = "PASS"
            if ns:
                why = "also under Not exercised: " + short(ns[0]["text"], 140)
    elif rs:
        st = "not run"
        why = short(rs[0]["text"])
    elif ns:
        st, why = "not run", short(ns[0]["text"])
    else:
        st, why = "not run", UNMAPPED
    return st, why


def atomic_write(path, data):
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--write", action="store_true", help='store the summary in links.json "acceptance"')
    a = ap.parse_args()
    global CFG, FEATURES
    CFG = fwconfig.load()
    FEATURES = CFG.features_root
    fdir = os.path.join(FEATURES, a.slug)
    plan, uat = os.path.join(fdir, "plan.md"), os.path.join(fdir, "uat.md")
    if not os.path.isdir(fdir):
        print(f"no feature folder features/{a.slug}/")
        return 1
    if not os.path.isfile(plan):
        print(f"features/{a.slug}/plan.md is missing")
        return 1
    items, err = parse_plan(plan)
    if err:
        print(f"features/{a.slug}/plan.md: {err}")
        return 1
    if not os.path.isfile(uat):
        print(f"features/{a.slug}/uat.md is missing ({len(items)} acceptance tests in plan.md, none run yet)")
        return 1
    known = {it["id"] for it in items}
    rows, notes, n_tables = parse_uat(uat, known)
    if not n_tables:
        print(f"note: uat.md has no results table with an 'Acceptance #' / '#' column and a 'Result' column; "
              f"only Not exercised / Not done lines are used")

    results = []
    for it in items:
        st, why = classify(it, rows, notes)
        results.append(dict(it, status=st, why=why))
        mark = " [needs founder]" if it["founder"] else ""
        print(f"{it['id']:>4}  {st:<8} {short(it['case'], 70)}{mark}" + (f"\n      - {why}" if why else ""))

    passed = [r for r in results if r["status"] == "PASS"]
    not_run = [r for r in results if r["status"] == "not run"]
    partial = [r for r in results if r["status"] == "partial"]
    failed = [r for r in results if r["status"] == "FAIL"]
    summary = f"{len(passed)}/{len(results)} passed"
    if partial:
        summary += f", partial: {', '.join(r['id'] for r in partial)}"
    if failed:
        summary += f", FAIL: {', '.join(r['id'] for r in failed)}"
    unmapped = [r for r in not_run if r["why"] == UNMAPPED]
    summary += f", not run: {', '.join(r['id'] for r in not_run) or 'none'}"
    if unmapped:
        summary += f" (of which no UAT row cites: {', '.join(r['id'] for r in unmapped)})"
    print("\n" + summary)

    if a.write and not n_tables:
        print("not writing: uat.md results are not keyed by acceptance id, so the counts above would understate coverage. "
              "Add an 'Acceptance #' column to the uat.md results table, then re-run with --write.")
        return 1
    if a.write:
        lp = os.path.join(fdir, "links.json")
        if not os.path.isfile(lp):
            print(f"no links.json in features/{a.slug}/; nothing written")
            return 1
        m = json.load(open(lp, encoding="utf-8"))  # re-read right before writing
        ent = lambda r: {"id": r["id"], "case": short(r["case"], 120), "why": r["why"]}
        m["acceptance"] = {
            "total": len(results), "passed": len(passed),
            "not_run": [ent(r) for r in not_run],
            "partial": [ent(r) for r in partial],
            "failed": [ent(r) for r in failed],
            "founder_hands": [r["id"] for r in results if r["founder"]],
            "source": CFG.rel(uat),
            "checked": dt.date.today().isoformat(),
        }
        m["updated"] = dt.date.today().isoformat()
        atomic_write(lp, m)
        print(f"wrote acceptance to features/{a.slug}/links.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
