#!/usr/bin/env python3
"""Gate B "Figma vs stage" check: Scry's diff judge on the approved proposal frames versus
screenshots of the built feature on your stage tier.

Needs a Scry account with API access to its diff service (see the README) and an
S3-compatible bucket the diff service can read screenshots from. All endpoints, ids and the
names of the environment variables that hold credentials come from feature-workflow.json
("diff_service" and "dashboard"; schema in scripts/README.md).

Usage:
  figma-vs-stage.py --slug <slug> --shots <dir> [--map map.json] [--tier basic|plus]
                    [--project <project id>] [--wallet <billing wallet>] [--dry-run]

For every frame in <features_root>/<slug>/figma/ledger.json (and pluginFile.frames, if any):
  1. find its stage screenshot in --shots by normalised name ("Orders / List · loaded"
     <-> orders-list-loaded.png) or by --map {"<frame name>": "<path>"}; a frame with no
     screenshot is reported under "Not compared" with the reason (a --map value that is not a
     path, e.g. {"Orders / List · empty": "skip: state no longer reachable"}, is taken as
     the reason);
  2. scales the screenshot to the frame's width (Pillow, else ffmpeg), keeps both images
     under <feature>/uat/figma-vs-stage/;
  3. puts both PNGs in the configured bucket (S3 API, SigV4, stdlib) under
     <project>/figma-vs-stage/<slug>/..., registers a pair (POST /api/pairs), starts a run
     (POST /api/agent/annotate?async=1, polls GET /api/agent/runs/<id> until terminal;
     a 200 sync answer is accepted too), then reads the run's issues
     (GET /api/issues?pair=<pair>) and saves the hybrid report;
  4. writes <feature>/uat/figma-vs-stage.md and sets links.json "figma_vs_stage".

Stage only: refuses a diff-service URL whose /healthz does not report env ==
diff_service.stage_env (default "staging").
Credentials are read from the environment variables the config names (never printed or stored):
  diff_service.token_env                 bearer token for the diff service
  diff_service.s3.access_key_env         S3 access key id for the bucket
  diff_service.s3.secret_key_env         S3 secret access key
Cost: each frame is one run at the chosen tier, billed to --wallet (default diff_service.wallet).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import fwconfig  # noqa: E402

# Optional: set FEATURE_WORKFLOW_IPV4_ONLY=1 on hosts with broken IPv6 egress.
if os.environ.get("FEATURE_WORKFLOW_IPV4_ONLY") == "1":
    _gai = socket.getaddrinfo
    socket.getaddrinfo = lambda *a, **k: [r for r in _gai(*a, **k) if r[0] == socket.AF_INET] or _gai(*a, **k)

CFG = None      # fwconfig.Config, loaded in main()
ROOT = None     # ops root
UA = "feature-workflow-figma-vs-stage/1"
BLOCKING = {"blocker", "major"}
TERMINAL = {"complete", "degraded", "errored"}


def die(msg: str) -> None:
    print(f"figma-vs-stage: {msg}", file=sys.stderr)
    sys.exit(1)


def norm(name: str) -> str:
    """'Orders / List · loaded' -> 'orders-list-loaded'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def read_secret(key: str) -> str:
    """Value of the environment variable named by config key `key` (e.g. diff_service.token_env).
    If that variable is unset, <NAME>_FILE may name a file holding the value."""
    name = CFG.need(key, "the name of an environment variable, not the secret itself")
    v = (os.environ.get(name) or "").strip()
    if v:
        return v
    f = os.environ.get(name + "_FILE")
    if f:
        try:
            with open(os.path.expanduser(f)) as fh:
                return fh.read().strip()
        except OSError:
            pass
    die(f"environment variable {name} (named by {key} in feature-workflow.json) is not set")


# ---------------------------------------------------------------- HTTP (diff service)
class Diff:
    def __init__(self, base: str, token: str):
        self.base, self._token = base.rstrip("/"), token

    def call(self, method: str, path: str, body=None, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}", "User-Agent": UA,
            **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        text = raw.decode("utf-8", "replace").replace(self._token, "<redacted>")
        try:
            return status, json.loads(text)
        except ValueError:
            return status, text

    def must(self, method, path, body=None, ok=(200,), timeout=60):
        status, js = self.call(method, path, body, timeout)
        if status not in ok:
            raise RuntimeError(f"{method} {path.split('?')[0]} -> HTTP {status}: {str(js)[:400]}")
        return status, js


# ---------------------------------------------------------------- bucket (S3 API, SigV4, stdlib)
class S3:
    """Minimal S3 PUT with AWS Signature V4, enough for R2, S3, MinIO and other S3-compatible stores."""

    def __init__(self, endpoint: str, region: str, access_key: str, secret_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.region = region or "auto"
        self._ak, self._sk = access_key, secret_key

    def _sign(self, key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str = "application/octet-stream"):
        u = urllib.parse.urlsplit(self.endpoint)
        path = "/" + "/".join(urllib.parse.quote(p, safe="-_.~") for p in [Bucket, *Key.split("/")])
        now = dt.datetime.now(dt.timezone.utc)
        amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(Body).hexdigest()
        headers = {"host": u.netloc, "content-type": ContentType, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        signed = ";".join(sorted(headers))
        canonical = "\n".join(["PUT", path, "", "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)), signed, payload_hash])
        scope = f"{day}/{self.region}/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        k = self._sign(("AWS4" + self._sk).encode(), day)
        for part in (self.region, "s3", "aws4_request"):
            k = self._sign(k, part)
        sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        auth = f"AWS4-HMAC-SHA256 Credential={self._ak}/{scope}, SignedHeaders={signed}, Signature={sig}"
        req = urllib.request.Request(f"{u.scheme}://{u.netloc}{path}", data=Body, method="PUT", headers={
            "Content-Type": ContentType, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date,
            "Authorization": auth, "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"bucket PUT {Key} -> HTTP {e.code}: {e.read()[:300]!r}") from None


def s3_client():
    endpoint = CFG.need("diff_service.s3.endpoint", "S3 API endpoint of the bucket the diff service reads")
    return S3(endpoint, CFG.get("diff_service.s3.region", "auto"),
              read_secret("diff_service.s3.access_key_env"), read_secret("diff_service.s3.secret_key_env"))


# ---------------------------------------------------------------- images
def png_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def fit_width(src: str, dst: str, width: int) -> str:
    """Copy src to dst as PNG, scaled to `width` if it differs. Returns what was done."""
    w, h = png_size(src)
    if w == width:
        shutil.copyfile(src, dst)
        return f"same width ({w}x{h})"
    nh = max(1, round(h * width / w))
    try:
        from PIL import Image
        with Image.open(src) as im:
            im.convert("RGB").resize((width, nh), Image.LANCZOS).save(dst, "PNG")
        how = "Pillow"
    except ImportError:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf", f"scale={width}:{nh}:flags=lanczos", dst], check=True)
        how = "ffmpeg"
    return f"scaled {w}x{h} -> {width}x{nh} ({how})"


def sha8(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:8]


# ---------------------------------------------------------------- matching
def ledger_frames(ledger: dict) -> list[dict]:
    out = []
    for f in ledger.get("frames") or []:
        out.append({**f, "fileKey": ledger.get("fileKey")})
    plug = ledger.get("pluginFile") or {}
    for f in plug.get("frames") or []:
        out.append({**f, "fileKey": plug.get("fileKey")})
    return out


def match_shots(frames, shots_dir, mapping):
    files = {}
    if shots_dir and os.path.isdir(shots_dir):
        for fn in sorted(os.listdir(shots_dir)):
            if fn.lower().endswith(".png"):
                files.setdefault(norm(os.path.splitext(fn)[0]), os.path.join(shots_dir, fn))
    result = []
    for f in frames:
        name = f["name"]
        if name in mapping:
            v = str(mapping[name])
            p = v if os.path.isabs(v) else os.path.join(shots_dir or ".", v)
            if os.path.isfile(p):
                result.append((f, os.path.abspath(p), None))
            elif os.path.isfile(v):
                result.append((f, os.path.abspath(v), None))
            else:
                why = re.sub(r"^skip:\s*", "", v) if not v.lower().endswith(".png") else f"--map file not found: {v}"
                result.append((f, None, why))
            continue
        key = norm(name)
        p = files.get(key)
        p = os.path.abspath(p) if p else None
        result.append((f, p, None if p else f"no screenshot named {key}.png in {shots_dir} and no --map entry"))
    return result


# ---------------------------------------------------------------- one frame
def run_frame(diff, s3, args, feature_dir, frame, shot, evdir):
    fk = norm(frame["name"])
    fig_png = os.path.join(feature_dir, frame["png"]) if frame.get("png") else None
    if not fig_png or not os.path.isfile(fig_png):
        return {"skip": f"Figma render missing: {frame.get('png')}"}
    fw, _ = png_size(fig_png)
    a = os.path.join(evdir, f"{fk}-figma.png")
    b = os.path.join(evdir, f"{fk}-stage.png")
    shutil.copyfile(fig_png, a)
    prep = fit_width(shot, b, fw)
    prefix = f"{args.project}/figma-vs-stage/{args.slug}"
    ka, kb = f"{prefix}/{fk}-figma-{sha8(a)}.png", f"{prefix}/{fk}-stage-{sha8(b)}.png"
    link_id = f"fvs-{args.slug}-{fk}"[:120]
    pair_id = (CFG.get("diff_service.pair_id_prefix") or "") + f"{args.project}-{link_id}"
    rec = {"frame": frame["name"], "node": frame.get("id"), "shot": shot, "prep": prep, "pair_id": pair_id,
           "link_id": link_id, "image_a": a, "image_b": b, "key_a": ka, "key_b": kb}
    if args.dry_run:
        rec["verdict"] = "dry run (not sent)"
        return rec
    for key, path in ((ka, a), (kb, b)):
        with open(path, "rb") as fh:
            s3.put_object(Bucket=args.bucket, Key=key, Body=fh.read(), ContentType="image/png")
    body = {"pair_id": pair_id, "project_id": args.project, "link_id": link_id,
            "name": f"{frame['name']} (Figma vs stage, {args.slug})", "image_a_key": ka, "image_b_key": kb}
    if args.tier == "plus" and frame.get("fileKey") and frame.get("id"):
        body.update(figma_file_key=frame["fileKey"], figma_node_id=frame["id"])
    diff.must("POST", "/api/pairs", body)
    annotate = {"pair_id": pair_id, "who": "figma-vs-stage", "trigger": "run", "tier": args.tier}
    if args.wallet:
        annotate["billing_wallet"] = args.wallet
    status, js = diff.must("POST", "/api/agent/annotate?async=1", annotate, ok=(200, 202), timeout=300)
    run_id = js.get("run_id")
    if not run_id:
        raise RuntimeError(f"annotate answered {status} without run_id: {str(js)[:300]}")
    rec["run_id"] = run_id
    deadline = time.time() + args.timeout
    run = {}
    while time.time() < deadline:
        _, run = diff.must("GET", f"/api/agent/runs/{run_id}")
        if run.get("terminal") or run.get("status") in TERMINAL:
            break
        time.sleep(8)
    else:
        raise RuntimeError(f"run {run_id} not terminal after {args.timeout}s (last status {run.get('status')})")
    rec.update(status=run.get("status"), tier=run.get("tier_effective"), cost_usd=run.get("cost_usd"),
               price_units=run.get("price_units"), degraded=run.get("degraded_reason"),
               credits=(run.get("price_units") or 0) * args.credits_per_unit if run.get("billable") else 0,
               counts=run.get("counts"))
    if run.get("status") == "errored":
        steps = [f"{s.get('step')}:{s.get('status')}:{s.get('detail')}" for s in run.get("pipeline_steps") or [] if s.get("status") != "ok"]
        raise RuntimeError(f"run {run_id} errored: {(run.get('workflow') or {}).get('error') or '; '.join(steps)[:300]}")
    _, iss = diff.must("GET", f"/api/issues?pair={urllib.parse.quote(pair_id)}")
    issues = [i for i in iss.get("issues") or [] if i.get("run_id") == run_id and i.get("status") != "dismissed"]
    rec["issues"] = [{"number": i.get("number"), "severity": i.get("severity") or i.get("suggested_severity"),
                      "labels": i.get("labels") or [], "note": (i.get("note") or "").strip(),
                      "status": i.get("status")} for i in issues]
    st, rep = diff.call("GET", f"/api/pairs/{urllib.parse.quote(pair_id)}/runs/{run_id}/hybrid-report")
    if st == 200:
        with open(os.path.join(evdir, f"{fk}-hybrid-report.json"), "w") as fh:
            json.dump(rep, fh, indent=1)
        rec["hybrid_report"] = os.path.join(evdir, f"{fk}-hybrid-report.json")
    return rec


# ---------------------------------------------------------------- report
def verdict(rec):
    iss = rec.get("issues") or []
    blocking = [i for i in iss if (i["severity"] or "") in BLOCKING]
    if not iss:
        return "matches what you approved", 0, 0
    if blocking:
        return f"differs here: {len(blocking)} blocking", len(blocking), len(iss) - len(blocking)
    return "matches, with minor differences", 0, len(iss)


def rel(p):
    return CFG.rel(p) if p else p


def viewer_link(args, link_id=None, issue=None):
    """Links into your dashboard, from dashboard.viewer_link_template / dashboard.issue_link_template.
    Placeholders: {stage_url} {project_id} {link_id} {pair_id} {issue}. Empty when not configured."""
    tpl = CFG.get("dashboard.issue_link_template" if issue is not None else "dashboard.viewer_link_template")
    if not tpl:
        return ""
    return tpl.format(stage_url=args.dash_url.rstrip("/"), project_id=args.project, link_id=link_id or "",
                      pair_id=((CFG.get("diff_service.pair_id_prefix") or "") + f"{args.project}-{link_id}") if link_id else "",
                      issue=issue if issue is not None else "")


def write_report(args, ledger, compared, failed, skipped, out_md):
    blocking = minor = 0
    for r in compared:
        _, b, m = verdict(r)
        blocking, minor = blocking + b, minor + m
    credits = sum(r.get("credits") or 0 for r in compared)
    usd = sum(r.get("cost_usd") or 0 for r in compared)
    not_compared = skipped + [(f, f"run failed: {e}") for f, e in failed]
    summary = (f"{len(compared)} frames compared, {blocking} blocking, {minor} minor, "
               f"{len(not_compared)} not compared")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig = (ledger.get("page") or {}).get("url") or ""
    lines = [f"# Figma vs stage - {args.slug}", "", f"**{summary}**", "",
             f"Run {now} · tier {args.tier} · stage diff service `{args.diff_url}` · project `{args.project}` · "
             f"{credits} credits (${usd:.4f} model cost)" + (f" billed to `{args.wallet}`" if args.wallet else ""),
             f"Figma page: {fig}" if fig else "", "",
             "Verdicts come from Scry's diff judge (Basic/Plus pipeline) comparing the approved "
             "Figma frame (image A) with the stage screenshot (image B). Blocking = blocker/major, minor = minor/nit "
             "(the judge's suggested severity; a person confirms it in triage). Check each finding against the two "
             "images before acting: viewport, scroll position and live data differences are capture artefacts, not drift.",
             ""]
    for r in compared:
        v, _, _ = verdict(r)
        link = viewer_link(args, link_id=r["link_id"]) or "(set dashboard.viewer_link_template to link the viewer)"
        lines += [f"## {r['frame']}", "",
                  f"- Figma node: `{r.get('node')}`",
                  f"- Stage screenshot: `{rel(r['shot'])}` ({r['prep']})",
                  f"- Verdict: **{v}**",
                  f"- Run: `{r.get('run_id')}` · {r.get('status')} · tier {r.get('tier')}"
                  f"{' · degraded: ' + r['degraded'] if r.get('degraded') else ''} · {r.get('credits')} credits · ${r.get('cost_usd') or 0:.4f}",
                  f"- Viewer (stage dashboard, sign in as a member of the project): {link}",
                  f"- Images sent: `{rel(r['image_a'])}` (A, Figma) · `{rel(r['image_b'])}` (B, stage)"
                  + (f" · hybrid report `{rel(r['hybrid_report'])}`" if r.get("hybrid_report") else ""), ""]
        if r.get("issues"):
            lines.append("| # | Severity | What differs |")
            lines.append("|---|---|---|")
            order = {"blocker": 0, "major": 1, "minor": 2, "nit": 3}
            for i in sorted(r["issues"], key=lambda i: order.get(i["severity"] or "", 4)):
                note = re.sub(r"\s+", " ", i["note"]).replace("|", "\\|")
                il = viewer_link(args, issue=i["number"]) if i.get("number") else ""
                num = (f"[{i['number']}]({il})" if il else str(i["number"])) if i.get("number") else "-"
                lines.append(f"| {num} | {i['severity'] or 'unrated'} | {note} |")
            lines.append("")
        else:
            lines += ["No differences found.", ""]
    lines += ["## Not compared", ""]
    if not_compared:
        lines += [f"- **{f['name']}** (`{f.get('id')}`): {why}" for f, why in not_compared]
    else:
        lines.append("- none")
    lines.append("")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w") as fh:
        fh.write("\n".join(l for l in lines if l is not None) + "\n")
    return summary, credits


def update_links(feature_dir, md_rel, summary):
    path = os.path.join(feature_dir, "links.json")
    try:
        with open(path) as fh:   # re-read right before writing: other sessions write this file too
            data = json.load(fh)
    except FileNotFoundError:
        data = {}
    data["figma_vs_stage"] = {"path": md_rel, "summary": summary,
                              "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    fd, tmp = tempfile.mkstemp(dir=feature_dir, prefix=".links.", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--shots", required=True, help="directory of stage screenshots (PNG)")
    ap.add_argument("--map", help="JSON {frame name: screenshot path | 'skip: reason'}")
    ap.add_argument("--tier", default="basic", choices=["basic", "plus"])
    ap.add_argument("--project", help="project the pairs live under (default diff_service.project_id)")
    ap.add_argument("--wallet", help="billing wallet that pays (default diff_service.wallet)")
    ap.add_argument("--diff-url", help="diff service base URL (default diff_service.base_url)")
    ap.add_argument("--dash-url", help="stage dashboard URL (default dashboard.stage_url)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait per run")
    ap.add_argument("--dry-run", action="store_true", help="match and prepare images only; no upload, no spend")
    args = ap.parse_args()
    global CFG, ROOT
    CFG = fwconfig.load()
    ROOT = CFG.root
    args.project = args.project or CFG.need("diff_service.project_id", "the project your pairs are registered under")
    args.wallet = args.wallet or CFG.get("diff_service.wallet", "")
    args.diff_url = args.diff_url or CFG.need("diff_service.base_url", "your stage diff-service URL")
    args.dash_url = args.dash_url or CFG.get("dashboard.stage_url", "")
    args.bucket = CFG.get("diff_service.bucket", "")
    args.credits_per_unit = int(CFG.get("diff_service.credits_per_unit", 1))
    stage_env = CFG.get("diff_service.stage_env", "staging")

    feature_dir = os.path.join(CFG.features_root, args.slug)
    ledger_path = os.path.join(feature_dir, "figma", "ledger.json")
    if not os.path.isfile(ledger_path):
        die(f"no ledger: {ledger_path}")
    with open(ledger_path) as fh:
        ledger = json.load(fh)
    mapping = {}
    if args.map:
        with open(args.map) as fh:
            mapping = json.load(fh)
    frames = ledger_frames(ledger)
    if not frames:
        die("ledger has no frames")

    diff = s3 = None
    if not args.dry_run:
        if not args.bucket:
            CFG.need("diff_service.bucket", "the bucket the diff service reads screenshots from")
        token = read_secret("diff_service.token_env")
        diff = Diff(args.diff_url, token)
        st, hz = diff.call("GET", "/healthz")
        if st != 200 or not isinstance(hz, dict) or hz.get("env") != stage_env:
            die(f"{args.diff_url}/healthz is not a {stage_env} deployment (HTTP {st}, env={getattr(hz, 'get', lambda k: None)('env')}); stage only")
        print(f"diff service: {hz.get('service')} {str(hz.get('commit'))[:7]}")
        s3 = s3_client()

    evdir = os.path.join(feature_dir, "uat", "figma-vs-stage")
    os.makedirs(evdir, exist_ok=True)
    compared, failed, skipped = [], [], []
    for frame, shot, why in match_shots(frames, args.shots, mapping):
        if not shot:
            skipped.append((frame, why))
            print(f"- {frame['name']}: not compared ({why})")
            continue
        print(f"- {frame['name']} <- {shot}", flush=True)
        try:
            rec = run_frame(diff, s3, args, feature_dir, frame, shot, evdir)
        except Exception as e:  # noqa: BLE001 - one bad frame must not hide the others
            failed.append((frame, f"{type(e).__name__}: {e}"))
            print(f"  FAILED: {e}")
            continue
        if rec.get("skip"):
            skipped.append((frame, rec["skip"]))
            print(f"  not compared ({rec['skip']})")
            continue
        compared.append(rec)
        print(f"  {verdict(rec)[0]} · run {rec.get('run_id')} · {rec.get('credits')} credits" if not args.dry_run else f"  {rec['prep']}")
    if args.dry_run:
        print(f"dry run: {len(compared)} would be compared, {len(skipped)} not compared")
        return
    out_md = os.path.join(feature_dir, "uat", "figma-vs-stage.md")
    summary, credits = write_report(args, ledger, compared, failed, skipped, out_md)
    update_links(feature_dir, CFG.rel(out_md), summary)
    print(f"{summary} · {credits} credits\nwrote {out_md}")
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
