#!/usr/bin/env python3
"""Feature hub: render <features_root>/*/links.json into one self-contained HTML page.

Usage (anywhere under the ops repo that holds feature-workflow.json):
    python3 feature-hub.py            # fetch live PR state with `gh api`, run hub_extras
    python3 feature-hub.py --offline  # skip GitHub and hub_extras, render from links.json only

Output: <features_root>/hub/index.html (stable path; republish that file to update the page).
Paths inside links.json are relative to the ops root (the directory of feature-workflow.json)
unless absolute. Config keys used: features_root, github_owner (owner for bare repo names in
links.json), repos[].github (an explicit "owner/name" for one repo), hub_artifact_url (shown in the
footer), hub_title, hub_safe_email_domains, hub_extras (see scripts/README.md).
"""
import argparse, datetime as dt, html, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import fwconfig  # noqa: E402

CFG = fwconfig.load()
ROOT = CFG.root
FEATURES = CFG.features_root
OUT = os.path.join(FEATURES, "hub", "index.html")
EXCERPT_EXT = (".md", ".log", ".txt", ".json")
EXCERPT_MAX_BYTES = 60_000
EXCERPT_MAX_CHARS = 16_000

SECRET_RES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\b(?:sk|pk|rk|phc|phx|ghp|gho|ghs|ghu|github_pat|sntrys|sntryu|xox[abprs]|glpat|AKIA)[_-]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)((?:token|secret|password|api[_-]?key)\s*[=:]\s*)[\"']?[A-Za-z0-9._\-/+]{16,}"),
]
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
SAFE_EMAIL_DOMAINS = {d.lower() for d in (CFG.get("hub_safe_email_domains") or ["example.com"])}


def redact(text):
    for rx in SECRET_RES:
        text = rx.sub(lambda m: (m.group(1) if m.groups() and m.group(1) else "") + "[redacted]", text)
    return EMAIL_RE.sub(lambda m: m.group(0) if m.group(1).lower() in SAFE_EMAIL_DOMAINS else "[email]", text)


def gh_json(path):
    try:
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except Exception:
        return None


REPO_SLUGS = {r.get("name"): r.get("github") for r in CFG.repos() if r.get("name") and r.get("github")}


def slug(repo):
    """owner/name for a links.json repo, which is either a bare name or already owner/name."""
    if "/" in repo:
        return repo
    if repo in REPO_SLUGS:
        return REPO_SLUGS[repo]
    owner = CFG.get("github_owner")
    if not owner:
        fwconfig.fail(f"links.json names repo '{repo}' without an owner; set 'github_owner' in {CFG.path}, "
                      f"a 'github' field on its repos entry, or write it as owner/name")
    return f"{owner}/{repo}"


def ci_conclusion(repo, sha):
    runs = gh_json(f"repos/{slug(repo)}/commits/{sha}/check-runs?per_page=100") or {}
    status = gh_json(f"repos/{slug(repo)}/commits/{sha}/status") or {}
    states = []
    for cr in runs.get("check_runs", []):
        if cr.get("status") != "completed":
            states.append("pending")
        else:
            c = cr.get("conclusion")
            states.append("pass" if c in ("success", "neutral", "skipped") else "fail" if c in ("failure", "timed_out", "action_required", "startup_failure") else "other")
    for st in status.get("statuses", []):
        states.append({"success": "pass", "failure": "fail", "error": "fail", "pending": "pending"}.get(st.get("state"), "other"))
    if not states:
        return "none"
    if "fail" in states:
        return "fail"
    if "pending" in states:
        return "pending"
    return "pass"


def fetch_pr(key):
    repo, number = key
    p = gh_json(f"repos/{slug(repo)}/pulls/{number}")
    if not p:
        return key, {"state": "unknown"}
    state = "merged" if p.get("merged_at") else p.get("state", "unknown")
    if p.get("draft") and state == "open":
        state = "draft"
    sha = (p.get("head") or {}).get("sha")
    return key, {
        "state": state, "title": p.get("title", ""), "base": (p.get("base") or {}).get("ref", ""),
        "merged_at": p.get("merged_at"), "updated_at": p.get("updated_at"),
        "ci": ci_conclusion(repo, sha) if sha else "none",
    }


def run_hub_extras(offline):
    """Optional "hub_extras" hook: a list of {"title": ..., "command": ...}. Each command runs from
    the ops root and prints an HTML fragment (e.g. a <section class="feat">) that is placed above the
    feature cards, e.g. the state of your synthetic checks or uptime monitor. Skipped with --offline.
    A command that fails or times out renders as a one-line note; nothing it prints is redacted, so
    it must not print secrets."""
    extras = CFG.get("hub_extras") or []
    out = []
    for x in extras:
        title = x.get("title") or x.get("command", "extra")
        if offline:
            out.append(f'<section class="feat"><h2>{e(title)}</h2><p class="dim">offline render</p></section>')
            continue
        try:
            r = subprocess.run(x["command"], shell=True, cwd=ROOT, capture_output=True, text=True, timeout=int(x.get("timeout", 60)))
            if r.returncode == 0 and r.stdout.strip():
                out.append(r.stdout)
                continue
            why = f"exit {r.returncode}"
        except Exception as err:  # noqa: BLE001
            why = type(err).__name__
        out.append(f'<section class="feat"><h2>{e(title)}</h2><p class="dim">hub_extras command gave no output ({e(why)})</p></section>')
    return "\n".join(out)


def load_manifests():
    out = []
    for slug in sorted(os.listdir(FEATURES)):
        f = os.path.join(FEATURES, slug, "links.json")
        if os.path.isfile(f):
            try:
                out.append(json.load(open(f)))
            except json.JSONDecodeError as e:
                print(f"skip {f}: {e}", file=sys.stderr)
    return out


def is_url(s):
    return isinstance(s, str) and s.startswith(("http://", "https://"))


def local_abs(p):
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def excerpt_for(p):
    if not p or is_url(p) or not p.endswith(EXCERPT_EXT):
        return None
    a = local_abs(p)
    try:
        if not os.path.isfile(a) or os.path.getsize(a) > EXCERPT_MAX_BYTES:
            return None
        t = open(a, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    t = redact(t)
    if len(t) > EXCERPT_MAX_CHARS:
        t = t[:EXCERPT_MAX_CHARS] + "\n… (truncated; full file at the path above)"
    return t


def latest_activity(m, prs):
    dates = [m.get("updated", "")]
    dates += [t.get("date", "") for t in m.get("tests", [])]
    dates += [r.get("date", "") for r in m.get("releases", [])]
    for p in m.get("prs", []):
        live = prs.get((p["repo"], p["number"]), {})
        dates += [(live.get("merged_at") or "")[:10], (live.get("updated_at") or "")[:10]]
    return max(d for d in dates if d) if any(dates) else ""


e = html.escape


def link_or_path(v, label=None):
    if not v:
        return ""
    if is_url(v):
        return f'<a href="{e(v)}" target="_blank" rel="noopener">{e(label or v)}</a>'
    return f'<code class="path" title="Local path in the ops repo, not reachable from the web">{e(v)}</code>'


def stage_class(cur):
    c = (cur or "").lower()
    if "research" in c:
        return "research"
    if c.startswith("6") or "released" in c or c.startswith("done"):
        return "shipped"
    if c.startswith(("4", "5")):
        return "testing"
    if c.startswith("3"):
        return "building"
    return "design"


def gate_class(txt):
    t = (txt or "").lower()
    if not t:
        return "none"
    if "pending" in t and "approved" not in t:
        return "pending"
    if "pending" in t:
        return "partial"
    return "ok"


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fu_overdue(fu, today):
    t = str(fu.get("trigger", ""))
    return fu.get("status", "open") == "open" and bool(ISO_DATE.match(t)) and t < today


def fu_sort_key(fu):
    t = str(fu.get("trigger", ""))
    return (0, t) if ISO_DATE.match(t) else (1, t.lower())


def fu_pill(fu, today):
    if fu.get("status") == "done":
        return '<span class="pill r-pass">done</span>'
    if fu_overdue(fu, today):
        return '<span class="pill r-fail">overdue</span>'
    return '<span class="pill r-partial">open</span>'


def render_checks(m):
    """Acceptance / guarantees / walkthrough / figma-vs-stage lines for one card."""
    out = []
    acc = m.get("acceptance") or {}
    if acc.get("total"):
        total, passed = acc.get("total", 0), acc.get("passed", 0)
        cls = "r-pass" if passed == total else "r-partial"
        bits = []
        for key, lab in (("failed", "FAIL"), ("partial", "partial"), ("not_run", "not run")):
            items = acc.get(key) or []
            if items:
                bits.append(f'<span class="accgrp"><b>{lab}:</b> ' + "; ".join(
                    f'<span title="{e(it.get("case", ""))}">#{e(str(it.get("id", "")))}</span>'
                    + (f' <span class="dim">({e(it.get("why", ""))})</span>' if it.get("why") else "") for it in items) + "</span>")
        founder = acc.get("founder_hands") or []
        if founder:
            bits.append(f'<span class="founder">needs founder: {", ".join("#" + e(str(x)) for x in founder)}</span>')
        src = f' · {link_or_path(acc["source"])}' if acc.get("source") else ""
        out.append(f'<li><span class="pill {cls}">Acceptance {passed}/{total}</span> {" ".join(bits)}{src}</li>')
    g = m.get("guarantees") or {}
    if g.get("total"):
        cls = "r-pass" if g.get("held") == g.get("total") else "r-fail"
        src = f' · {link_or_path(g["source"])}' if g.get("source") else ""
        out.append(f'<li><span class="pill {cls}">Guarantees held {g.get("held", 0)}/{g["total"]}</span>{src}</li>')
    w = m.get("walkthrough") or {}
    if w.get("url") or w.get("mp4"):
        parts = []
        if w.get("url"):
            parts.append(link_or_path(w["url"], "Walkthrough"))
        if w.get("mp4"):
            parts.append("video " + link_or_path(w["mp4"]))
        out.append(f'<li><span class="kind">UAT walkthrough</span> {" · ".join(parts)}</li>')
    fs = m.get("figma_vs_stage") or {}
    if fs.get("path") or fs.get("summary"):
        out.append(f'<li><span class="kind">Figma vs stage</span> {e(fs.get("summary", ""))}'
                   + (f' · {link_or_path(fs["path"], "report")}' if fs.get("path") else "") + "</li>")
    return f'<ul class="checks">{"".join(out)}</ul>' if out else ""


def render_followups(m, today):
    fus = m.get("followups") or []
    if not fus:
        return ""
    fus = sorted(fus, key=lambda f: (f.get("status") == "done", fu_sort_key(f)))
    n_open = sum(f.get("status", "open") == "open" for f in fus)
    rows = "".join(
        f'<li class="{"done" if f.get("status") == "done" else ""}"><div class="trow">{fu_pill(f, today)}<code>{e(str(f.get("id", "")))}</code>'
        f'<span class="dim">{e(str(f.get("trigger", "")))} · {e(f.get("owner", ""))}'
        f'{" · closed " + e(f["closed"]) if f.get("closed") else ""}</span></div>'
        f'<p>{e(f.get("what", ""))}</p>{"<div class=ev>" + link_or_path(f["source"]) + "</div>" if f.get("source") else ""}</li>'
        for f in fus)
    return f'<section><h3>Follow-ups <span class="count">{n_open} open</span></h3><ul class="tests fus">{rows}</ul></section>'


def render_waiting(manifests, today):
    rows = []
    for m in manifests:
        for f in m.get("followups") or []:
            if f.get("status", "open") == "open":
                rows.append((m, f))
    rows.sort(key=lambda mf: (fu_sort_key(mf[1]), mf[0].get("slug", "")))
    if not rows:
        return '<section class="panel waiting"><h2>Waiting on</h2><p class="dim">No open follow-ups.</p></section>'
    trs = "".join(
        f'<tr class="{"overdue" if fu_overdue(f, today) else ""}"><td class="when">{fu_pill(f, today)} {e(str(f.get("trigger", "")))}</td>'
        f'<td><a href="#{e(m.get("slug", ""))}">{e(m.get("title", m.get("slug", "")))}</a>'
        f'{" <span class=dim>(work item)</span>" if m.get("kind") == "work" else ""}</td>'
        f'<td><code>{e(str(f.get("id", "")))}</code></td><td>{e(f.get("what", ""))}</td><td>{e(f.get("owner", ""))}</td></tr>'
        for m, f in rows)
    n_over = sum(fu_overdue(f, today) for _, f in rows)
    return (f'<section class="panel waiting" id="waiting-on"><h2>Waiting on <span class="count">{len(rows)} open'
            f'{", " + str(n_over) + " overdue" if n_over else ""}</span></h2>'
            f'<p class="dim">Every open follow-up across all folders, soonest date first; condition-based triggers after the dated ones. '
            f'Mark one done with <code>followups.py --done &lt;slug&gt; &lt;id&gt;</code>.</p>'
            f'<div class="tablewrap"><table class="wait"><thead><tr><th>Trigger</th><th>Feature</th><th>Id</th><th>What</th><th>Owner</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div></section>')


def render(manifests, prs, excerpts, generated, offline, extras_html=""):
    today = generated[:10]
    feats, works = [], []
    for m in manifests:
        m["_latest"] = latest_activity(m, prs)
        (works if m.get("kind") == "work" else feats).append(m)
    feats.sort(key=lambda m: m["_latest"], reverse=True)
    works.sort(key=lambda m: m["_latest"], reverse=True)
    all_fus = [f for m in manifests for f in m.get("followups") or [] if f.get("status", "open") == "open"]
    n_fu, n_fu_over = len(all_fus), sum(fu_overdue(f, today) for f in all_fus)

    n_open = n_merged = n_ci_fail = n_test_bad = 0
    seen = set()
    for m in feats:
        for p in m.get("prs", []):
            k = (p["repo"], p["number"])
            if k in seen:
                continue
            seen.add(k)
            live = prs.get(k, {})
            n_open += live.get("state") in ("open", "draft")
            n_merged += live.get("state") == "merged"
            n_ci_fail += live.get("ci") == "fail" and live.get("state") in ("open", "draft")
        n_test_bad += sum(t.get("result") in ("fail", "blocked") for t in m.get("tests", []))

    def card(m):
        st = m.get("stage") or {}
        cur = st.get("current", "") if isinstance(st, dict) else str(st)
        gates = ""
        if isinstance(st, dict):
            for g, lab in (("gate_a", "Gate A"), ("gate_b", "Gate B")):
                if st.get(g):
                    gates += f'<span class="gate g-{gate_class(st[g])}"><b>{lab}</b> {e(st[g])}</span>'
        deck = m.get("deck") or {}
        top = []
        if deck.get("url"):
            top.append(f'<a class="btn" href="{e(deck["url"])}" target="_blank" rel="noopener">Narrated deck</a>')
        for fg in m.get("figma", []):
            top.append(f'<a class="btn ghost" href="{e(fg["url"])}" target="_blank" rel="noopener" title="{e(fg["label"])}">Figma · {e(fg["label"].split("·")[-1].strip())}</a>')
        mp4 = f'<div class="meta">Deck video: {link_or_path(deck["mp4"])}</div>' if deck.get("mp4") else ""

        # PRs grouped by repo
        by_repo = {}
        for p in m.get("prs", []):
            by_repo.setdefault(p["repo"], []).append(p)
        pr_html = ""
        for repo, items in by_repo.items():
            rows = ""
            for p in items:
                live = prs.get((p["repo"], p["number"]), {})
                state = live.get("state", "offline" if offline else "unknown")
                ci = live.get("ci", "none")
                when = (live.get("merged_at") or "")[:10]
                base = live.get("base", "")
                title = live.get("title") or ""
                rows += (
                    f'<li><a href="{e(p["url"])}" target="_blank" rel="noopener" class="num">#{p["number"]}</a>'
                    f'<span class="pill s-{e(state)}">{e(state)}</span>'
                    f'<span class="pill ci ci-{e(ci)}" title="Head commit checks">CI {e({"none": "–"}.get(ci, ci))}</span>'
                    f'<span class="role" title="{e(title)}">{e(p.get("role", ""))}</span>'
                    f'<span class="dim">{e("→ " + base if base else "")}{e(" · " + when if when else "")}</span></li>'
                )
            pr_html += f'<div class="repo"><h4>{e(repo)}</h4><ul class="prs">{rows}</ul></div>'
        pr_block = f'<section><h3>Pull requests <span class="count">{len(m.get("prs", []))}</span></h3>{pr_html}</section>' if pr_html else ""

        tests = sorted(m.get("tests", []), key=lambda t: t.get("date", ""), reverse=True)
        t_rows = ""
        for t in tests:
            ev = t.get("evidence", "")
            ex = ""
            if ev in excerpts:
                ex = f'<details class="ex" data-src="{e(ev)}"><summary>Show excerpt</summary><pre></pre></details>'
            t_rows += (
                f'<li><div class="trow"><span class="pill r-{e(t.get("result", ""))}">{e(t.get("result", ""))}</span>'
                f'<span class="kind">{e(t.get("kind", ""))}</span><b>{e(t.get("label", ""))}</b>'
                f'<span class="dim">{e(t.get("date", ""))}</span></div>'
                f'<p>{e(t.get("summary", ""))}</p><div class="ev">Evidence: {link_or_path(ev)}</div>{ex}</li>'
            )
        t_block = f'<section><h3>Tests <span class="count">{len(tests)}</span></h3><ul class="tests">{t_rows}</ul></section>' if t_rows else ""

        rels = sorted(m.get("releases", []), key=lambda r: r.get("date", ""), reverse=True)
        r_rows = "".join(
            f'<li><span class="dim">{e(r.get("date", ""))}</span> {e(r.get("label", ""))}'
            f'{" <code>" + e(r["commit"]) + "</code>" if r.get("commit") else ""} · {link_or_path(r.get("path_or_url", ""), "record")}</li>'
            for r in rels)
        r_block = f'<section><h3>Releases</h3><ul class="plain">{r_rows}</ul></section>' if r_rows else ""

        docs = m.get("docs", [])
        d_rows = "".join(f'<li>{e(d["label"])}: {link_or_path(d.get("path_or_url", ""), "open")}</li>' for d in docs)
        d_block = f'<section><h3>Docs</h3><ul class="plain">{d_rows}</ul></section>' if d_rows else ""

        fu_block = render_followups(m, today)
        checks = render_checks(m)
        search = " ".join([m.get("slug", ""), m.get("title", ""), cur, m.get("kind", "feature"), *(p["repo"] + " #" + str(p["number"]) + " " + p.get("role", "") for p in m.get("prs", []))]).lower()
        return (f'''
<article class="feat st-{stage_class(cur)}{' work' if m.get('kind') == 'work' else ''}" data-search="{e(search)}" id="{e(m.get("slug", ""))}">
  <header>
    <div class="h">
      <h2>{e(m.get("title", m.get("slug", "")))}</h2>
      <div class="slug"><code>features/{e(m.get("slug", ""))}/</code> · last activity {e(m["_latest"])}</div>
    </div>
    <div class="stagewrap"><span class="stage">{e(cur)}</span>{gates}</div>
  </header>
  {'<div class="links">' + "".join(top) + '</div>' if top else ''}{mp4}{checks}
  <div class="grid">{fu_block}{pr_block}{t_block}{r_block}{d_block}</div>
</article>''')

    cards = [card(m) for m in feats]
    work_html = ""
    if works:
        work_html = (f'<details class="workitems" id="work-items"><summary><h2>Work items <span class="count">{len(works)}</span></h2>'
                     f'<span class="dim">Releases, evals, research and tooling folders; not product features, not in the counts above.</span></summary>'
                     f'<div class="worklist">{"".join(card(m) for m in works)}</div></details>')

    data = json.dumps(excerpts).replace("</", "<\\/")
    mode = "offline render (PR state not fetched)" if offline else "PR state live from GitHub at generation time"
    return TEMPLATE.format(
        generated=e(generated), mode=e(mode), n_feat=len(feats), n_work=len(works), n_fu=n_fu, n_fu_over=n_fu_over,
        fu_cls="bad" if n_fu_over else "", waiting_html=render_waiting(manifests, today), work_html=work_html, n_open=n_open, n_merged=n_merged,
        n_ci_fail=n_ci_fail, n_test_bad=n_test_bad,
        ci_cls="bad" if n_ci_fail else "", t_cls="bad" if n_test_bad else "", cards="\n".join(cards), data=data,
        extras_html=extras_html, title=e(CFG.get("hub_title") or "Feature hub"), footer_extra=footer_extra())


def footer_extra():
    url = CFG.get("hub_artifact_url")
    return f' Published at <a href="{e(url)}">{e(url)}</a>.' if url else ""


TEMPLATE = """<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@600;700&display=swap">
<style>
:root {{
  --ground:#f4f6f5; --surface:#ffffff; --ink:#18211e; --muted:#5b6964; --line:#d9e0dc; --accent:#2c6b5a; --accent-ink:#ffffff;
  --pass:#1d7446; --pass-bg:#e1f2e8; --fail:#b0271f; --fail-bg:#fbe4e2; --warn:#955400; --warn-bg:#fcefd9;
  --block:#55606b; --block-bg:#e7eaee; --merged:#6a47b0; --merged-bg:#eee8fa; --open:#1d7446; --open-bg:#e1f2e8;
  --code-bg:#eef2f0;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif; --cond:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  color-scheme:dark; --ground:#101513; --surface:#171e1b; --ink:#e3ebe7; --muted:#95a39d; --line:#2a3531; --accent:#6fc2a7; --accent-ink:#0d1512;
  --pass:#6fd39a; --pass-bg:#16301f; --fail:#ff8f86; --fail-bg:#3a1917; --warn:#f0b35c; --warn-bg:#352512;
  --block:#aab4bd; --block-bg:#252c33; --merged:#b9a0f0; --merged-bg:#2a2340; --open:#6fd39a; --open-bg:#16301f; --code-bg:#1f2824;
}} }}
:root[data-theme="dark"] {{
  color-scheme:dark; --ground:#101513; --surface:#171e1b; --ink:#e3ebe7; --muted:#95a39d; --line:#2a3531; --accent:#6fc2a7; --accent-ink:#0d1512;
  --pass:#6fd39a; --pass-bg:#16301f; --fail:#ff8f86; --fail-bg:#3a1917; --warn:#f0b35c; --warn-bg:#352512;
  --block:#aab4bd; --block-bg:#252c33; --merged:#b9a0f0; --merged-bg:#2a2340; --open:#6fd39a; --open-bg:#16301f; --code-bg:#1f2824;
}}
* {{ box-sizing:border-box; }}
body {{ background:var(--ground); color:var(--ink); font:14px/1.5 var(--sans); padding-inline:16px; padding-block:24px 48px; }}
.wrap {{ max-width:1180px; margin:0 auto; display:flex; flex-direction:column; gap:18px; }}
a {{ color:var(--accent); }}
a:focus-visible, input:focus-visible, summary:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}
code {{ font-family:var(--mono); font-size:12.5px; background:var(--code-bg); padding:1px 5px; border-radius:4px; overflow-wrap:anywhere; }}
.top {{ display:flex; flex-wrap:wrap; align-items:flex-end; justify-content:space-between; gap:12px 24px; }}
h1 {{ font:700 30px/1.1 var(--cond); margin:0; letter-spacing:.01em; text-wrap:balance; }}
.sub {{ color:var(--muted); margin:4px 0 0; }}
.search {{ flex:1 1 260px; max-width:380px; }}
.search input {{ width:100%; font:inherit; padding:9px 12px; border:1px solid var(--line); border-radius:8px; background:var(--surface); color:var(--ink); }}
.stats {{ display:flex; flex-wrap:wrap; gap:8px 28px; padding:12px 0; border-block:1px solid var(--line); font-variant-numeric:tabular-nums; }}
.stats div {{ display:flex; align-items:baseline; gap:6px; color:var(--muted); }}
.stats b {{ font:600 20px var(--cond); color:var(--ink); }}
.stats .bad b {{ color:var(--fail); }}
.feat {{ background:var(--surface); border:1px solid var(--line); border-left:4px solid var(--c, var(--line)); border-radius:10px; padding:16px 18px; display:flex; flex-direction:column; gap:12px; }}
.st-shipped {{ --c:var(--pass); }} .st-building {{ --c:var(--accent); }} .st-testing {{ --c:var(--warn); }} .st-research {{ --c:var(--block); }} .st-design {{ --c:var(--merged); }}
.feat header {{ display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px 16px; }}
h2 {{ font:600 20px/1.2 var(--cond); margin:0; text-wrap:balance; }}
.slug {{ color:var(--muted); font-size:12.5px; margin-top:2px; }}
.stagewrap {{ display:flex; flex-wrap:wrap; gap:6px; align-items:flex-start; max-width:100%; }}
.stage {{ font-weight:600; font-size:12.5px; padding:3px 9px; border-radius:999px; background:var(--code-bg); color:var(--c, var(--ink)); }}
.gate {{ font-size:12px; padding:3px 9px; border-radius:999px; border:1px solid var(--line); color:var(--muted); }}
.gate b {{ color:var(--ink); font-weight:600; }}
.g-ok {{ background:var(--pass-bg); border-color:transparent; }} .g-pending {{ background:var(--warn-bg); border-color:transparent; }} .g-partial {{ background:var(--warn-bg); border-color:transparent; }}
.links {{ display:flex; flex-wrap:wrap; gap:8px; }}
.btn {{ font-size:13px; font-weight:500; text-decoration:none; padding:6px 12px; border-radius:7px; background:var(--accent); color:var(--accent-ink); }}
.btn.ghost {{ background:transparent; color:var(--accent); border:1px solid var(--line); }}
.meta {{ font-size:12.5px; color:var(--muted); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 440px), 1fr)); gap:14px 28px; }}
section h3 {{ font:600 12px var(--sans); text-transform:uppercase; letter-spacing:.07em; color:var(--muted); margin:0 0 8px; }}
.count {{ font-variant-numeric:tabular-nums; color:var(--ink); }}
.repo + .repo {{ margin-top:10px; }}
.repo h4 {{ margin:0 0 4px; font:500 12.5px var(--mono); color:var(--ink); }}
ul {{ list-style:none; margin:0; padding:0; }}
.prs li {{ display:flex; flex-wrap:wrap; align-items:center; gap:4px 8px; padding:3px 0; border-top:1px dashed var(--line); font-variant-numeric:tabular-nums; }}
.prs li:first-child {{ border-top:0; }}
.num {{ font-family:var(--mono); font-weight:500; min-width:3.2em; }}
.role {{ flex:1 1 160px; min-width:0; }}
.dim {{ color:var(--muted); font-size:12.5px; }}
.pill {{ font-size:11.5px; font-weight:600; padding:1px 8px; border-radius:999px; text-transform:lowercase; white-space:nowrap; background:var(--block-bg); color:var(--block); }}
.s-merged {{ background:var(--merged-bg); color:var(--merged); }} .s-open {{ background:var(--open-bg); color:var(--open); }} .s-draft {{ background:var(--warn-bg); color:var(--warn); }}
.ci-pass, .r-pass {{ background:var(--pass-bg); color:var(--pass); }} .ci-fail, .r-fail {{ background:var(--fail-bg); color:var(--fail); }}
.ci-pending, .r-partial {{ background:var(--warn-bg); color:var(--warn); }} .r-blocked {{ background:var(--block-bg); color:var(--block); }}
.tests li {{ padding:7px 0; border-top:1px dashed var(--line); }}
.tests li:first-child {{ border-top:0; padding-top:0; }}
.trow {{ display:flex; flex-wrap:wrap; align-items:center; gap:4px 8px; }}
.kind {{ font:500 11px var(--mono); color:var(--muted); text-transform:uppercase; }}
.tests p {{ margin:3px 0 2px; }}
.ev {{ font-size:12.5px; color:var(--muted); }}
.ex summary {{ cursor:pointer; font-size:12.5px; color:var(--accent); margin-top:3px; }}
.ex pre {{ max-height:360px; overflow:auto; background:var(--code-bg); padding:10px; border-radius:6px; font:12px/1.45 var(--mono); white-space:pre-wrap; overflow-wrap:anywhere; }}
.plain li {{ padding:2px 0; }}
.empty {{ color:var(--muted); padding:24px 0; }}
footer {{ color:var(--muted); font-size:12.5px; }}
.stats a {{ color:inherit; text-decoration:none; display:flex; align-items:baseline; gap:6px; }}
.stats a:hover {{ color:var(--accent); }}
.panel {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:16px 18px; display:flex; flex-direction:column; gap:8px; }}
.waiting {{ border-left:4px solid var(--warn); }}
.waiting p {{ margin:0; }}
.tablewrap {{ overflow-x:auto; }}
table.wait {{ width:100%; border-collapse:collapse; font-size:13px; }}
.wait th {{ text-align:left; font:600 11.5px var(--sans); text-transform:uppercase; letter-spacing:.06em; color:var(--muted); padding:4px 8px 6px 0; border-bottom:1px solid var(--line); }}
.wait td {{ padding:6px 8px 6px 0; border-top:1px dashed var(--line); vertical-align:top; }}
.wait td.when {{ white-space:nowrap; font-variant-numeric:tabular-nums; }}
.wait tr.overdue td {{ background:var(--fail-bg); }}
.wait tr.overdue td.when {{ color:var(--fail); font-weight:600; }}
@media (max-width:640px) {{ .wait thead {{ display:none; }} .wait tr {{ display:block; padding:6px 0; border-top:1px dashed var(--line); }} .wait td {{ display:inline; border:0; padding:0 6px 0 0; }} .wait td:nth-child(4) {{ display:block; }} }}
.checks {{ display:flex; flex-direction:column; gap:4px; font-size:13px; }}
.checks li {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 8px; }}
.checks .pill {{ text-transform:none; }}
.accgrp b {{ font-weight:600; }}
.founder {{ font-size:11.5px; font-weight:600; padding:1px 8px; border-radius:999px; background:var(--merged-bg); color:var(--merged); }}
.fus li.done p {{ color:var(--muted); text-decoration:line-through; }}
.workitems {{ border-top:1px solid var(--line); padding-top:12px; }}
.workitems > summary {{ cursor:pointer; display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 12px; list-style:none; }}
.workitems > summary::-webkit-details-marker {{ display:none; }}
.workitems > summary h2::before {{ content:"\\25B8  "; color:var(--muted); }}
.workitems[open] > summary h2::before {{ content:"\\25BE  "; }}
.worklist {{ display:flex; flex-direction:column; gap:14px; margin-top:12px; }}
</style>
<div class="wrap">
  <div class="top">
    <div>
      <h1>{title}</h1>
      <p class="sub">Every feature folder with its deck, Figma pages, PRs, tests, acceptance coverage, follow-ups and releases. Generated {generated} UTC · {mode}.</p>
    </div>
    <label class="search" for="q"><input id="q" type="search" placeholder="Filter: feature, repo, PR number, stage" autocomplete="off"></label>
  </div>
  <div class="stats">
    <div><b>{n_feat}</b> features</div>
    <div><b>{n_open}</b> open PRs</div>
    <div><b>{n_merged}</b> merged PRs</div>
    <div class="{ci_cls}"><b>{n_ci_fail}</b> open PRs with failing CI</div>
    <div class="{t_cls}"><b>{n_test_bad}</b> failed or blocked tests</div>
    <div class="{fu_cls}"><a href="#waiting-on"><b>{n_fu}</b> open follow-ups, <b>{n_fu_over}</b> overdue</a></div>
    <div><a href="#work-items"><b>{n_work}</b> work items</a></div>
  </div>
{waiting_html}
  <main id="list" style="display:flex;flex-direction:column;gap:14px">
{extras_html}
{cards}
{work_html}
  </main>
  <p class="empty" id="none" hidden>No feature matches that filter.</p>
  <footer>Source: <code>&lt;features_root&gt;/&lt;slug&gt;/links.json</code>. Regenerate with <code>feature-hub.py</code>, then republish <code>&lt;features_root&gt;/hub/index.html</code>.{footer_extra} Grey code paths are local to the ops repo and not reachable from the web.</footer>
</div>
<script type="application/json" id="excerpts">{data}</script>
<script>
(function () {{
  var ex = {{}};
  try {{ ex = JSON.parse(document.getElementById('excerpts').textContent); }} catch (err) {{}}
  document.querySelectorAll('details.ex').forEach(function (d) {{
    d.addEventListener('toggle', function () {{
      var pre = d.querySelector('pre');
      if (d.open && !pre.textContent) pre.textContent = ex[d.dataset.src] || '(excerpt unavailable)';
    }});
  }});
  var q = document.getElementById('q'), cards = document.querySelectorAll('.feat'), none = document.getElementById('none');
  function apply() {{
    var terms = q.value.toLowerCase().trim().split(/\\s+/).filter(Boolean), shown = 0;
    cards.forEach(function (c) {{
      var hay = c.dataset.search + ' ' + c.textContent.toLowerCase();
      var ok = terms.every(function (t) {{ return hay.indexOf(t) !== -1; }});
      c.hidden = !ok; shown += ok;
    }});
    var wi = document.getElementById('work-items');
    if (wi && terms.length && wi.querySelector('.feat:not([hidden])')) wi.open = true;
    none.hidden = shown > 0;
    try {{ localStorage.setItem('hub-filter', q.value); }} catch (err) {{}}
  }}
  try {{ q.value = localStorage.getItem('hub-filter') || ''; }} catch (err) {{}}
  q.addEventListener('input', apply);
  apply();
}})();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="do not call gh; PR state shows as offline")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    manifests = load_manifests()
    keys = sorted({(p["repo"], p["number"]) for m in manifests for p in m.get("prs", [])})
    prs = {}
    if not a.offline and keys:
        with ThreadPoolExecutor(max_workers=8) as pool:
            prs = dict(pool.map(fetch_pr, keys))
    excerpts = {}
    for m in manifests:
        for t in m.get("tests", []):
            ev = t.get("evidence", "")
            if ev and ev not in excerpts:
                x = excerpt_for(ev)
                if x:
                    excerpts[ev] = x
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    page = render(manifests, prs, excerpts, generated, a.offline, run_hub_extras(a.offline))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(page)
    unknown = [f"{r}#{n}" for (r, n), v in prs.items() if v.get("state") == "unknown"]
    print(f"wrote {a.out}: {sum(m.get('kind') != 'work' for m in manifests)} features + {sum(m.get('kind') == 'work' for m in manifests)} work items, {len(keys)} PRs, {len(excerpts)} excerpts" + (f"; PR lookups failed: {', '.join(unknown)}" if unknown else ""))


if __name__ == "__main__":
    main()
