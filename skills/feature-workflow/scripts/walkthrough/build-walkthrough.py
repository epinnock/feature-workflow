#!/usr/bin/env python3
"""Build the Gate B walkthrough: a narrated, captioned MP4 of a recorded stage run + a small HTML page.

Inputs come from a Playwright walkthrough spec that uses the step recorder in this directory
(walk.ts, copied into your app repo): the recorded .webm and <report>/steps.json with per-step
start/end offsets and screenshots, plus a narration.md written in the founder's words:

    ## Step 1
    Thirty to sixty words spoken over step one ...
    ## Step 2 - anything after the number is ignored
    ...

Usage:
  build-walkthrough.py --video video.webm --steps report/steps.json --narration narration.md \\
      --out <features_root>/<slug>/uat/walkthrough.mp4 --title "Order history on stage, YYYY-MM-DD"
  [--voice Charon] [--model pro] [--style "..."] [--date YYYY-MM-DD] [--env stage]
  [--lead-ms N] [--speedup-over 20] [--work DIR] [--html PATH] [--no-tts]

What it does:
  1. TTS per step with the narrated-deck skill's tts.py (Gemini; key lookup is in its docstring),
     found at --tts, else $NARRATED_DECK_TTS, else <tts.narrated_deck_dir>/assets/tts.py from
     feature-workflow.json, else ~/.claude/skills/narrated-deck/assets/tts.py; cached in <work>/audio/step-NN.wav keyed by the text, so re-runs only re-voice edited steps.
  2. Lines the video up with steps.json: if the spec called startWalk(meta, page), a magenta sync
     flash is found in the video and `lag = flash time - syncMarkMs`; else steps.json videoLeadMs;
     --lead-ms overrides both. The screencast then drifts behind the wall clock while pages load,
     so each step's end is refined by finding its end-of-step screenshot in the video (steps stay
     contiguous); --no-align cuts on the offsets alone.
  3. Per step: cut [lag+startMs, lag+endMs], hold the last frame until narration + 0.6 s has played
     (segment = max(narration + 0.6, real step time)); a real step longer than --speedup-over
     seconds and longer than its narration is played faster to fit (caption says so).
     Caption strip: "Step N of M", the step name, PASS/FAIL, and "<env> · <date>".
  4. 1.5 s title card + segments + 2 s end card (PASS/FAIL per step); H.264 yuv420p ≤1440x900,
     AAC; bitrate capped so 3 minutes stays under ~60 MB.
  5. walkthrough.html next to the MP4: title, video, per-step status/name/narration/screenshot
     (screenshots inlined as base64 while the page stays under 12 MB, else relative paths).

Stdlib + ffmpeg/ffprobe only. Fonts: DejaVu Sans by default; set WALKTHROUGH_FONT and
WALKTHROUGH_FONT_BOLD to other .ttf paths if your system keeps fonts elsewhere.
"""
import argparse, base64, datetime, hashlib, html, json, os, pathlib, re, shutil, subprocess, sys, wave

FONT = os.environ.get("WALKTHROUGH_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = os.environ.get("WALKTHROUGH_FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FALLBACK_TTS = pathlib.Path.home() / ".claude/skills/narrated-deck/assets/tts.py"


def resolve_tts(cli):
    """--tts, $NARRATED_DECK_TTS, feature-workflow.json tts.narrated_deck_dir, then the default install."""
    if cli:
        return pathlib.Path(cli), "--tts"
    if os.environ.get("NARRATED_DECK_TTS"):
        return pathlib.Path(os.environ["NARRATED_DECK_TTS"]), "NARRATED_DECK_TTS"
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    try:
        import fwconfig
        cfg = fwconfig.load(required=False)
    except SystemExit:
        cfg = None
    if cfg and cfg.get("tts.narrated_deck_dir"):
        d = pathlib.Path(cfg.resolve(cfg.get("tts.narrated_deck_dir")))
        for cand in (d / "assets" / "tts.py", d / "skills" / "narrated-deck" / "assets" / "tts.py"):
            if cand.exists():
                return cand, "tts.narrated_deck_dir"
        return d / "assets" / "tts.py", "tts.narrated_deck_dir"
    return FALLBACK_TTS, "default install"
DEFAULT_STYLE = ("Speak clearly and warmly at a measured pace, like someone showing a colleague a "
                 "finished feature. Pause briefly between sentences.")
FPS = 25
PAUSE = 0.6
TITLE_SEC, END_SEC = 1.5, 2.0
MAX_W, MAX_H = 1440, 900
HTML_BUDGET = 12 * 1024 * 1024
SYNC_RGB = (255, 0, 255)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"command failed ({r.returncode}): {' '.join(map(str, cmd[:6]))} ...\n{r.stderr[-2000:]}")
    return r.stdout


def probe(path):
    out = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]))
    v = next(s for s in out["streams"] if s["codec_type"] == "video")
    dur = float(out["format"].get("duration") or v.get("duration") or 0)
    if not dur:  # Playwright webm without a duration header: count by decoding
        last = run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "frame=pts_time",
                    "-of", "csv=p=0", str(path)]).split()
        dur = float(last[-1]) if last else 0
    return int(v["width"]), int(v["height"]), dur


def wav_seconds(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / float(w.getframerate())


def esc(p):
    """Escape a value for use inside an ffmpeg filter argument."""
    return str(p).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def parse_narration(text):
    parts = re.split(r"^## Step (\d+)[^\n]*\n", text, flags=re.M)
    return {int(parts[i]): " ".join(parts[i + 1].split()) for i in range(1, len(parts) - 1, 2)}


def find_sync_flash(video, search_sec=40.0):
    """(first, after-last) seconds of the magenta sync flash in the video, or None."""
    w, h, fps = 16, 10, 50
    p = subprocess.run(["ffmpeg", "-v", "error", "-t", str(search_sec), "-i", str(video),
                        "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True)
    data, size = p.stdout, w * h * 3
    first = None
    for i in range(len(data) // size):
        fr = data[i * size:(i + 1) * size]
        hits = sum(1 for k in range(0, size, 3)
                   if abs(fr[k] - SYNC_RGB[0]) < 40 and fr[k + 1] < 60 and abs(fr[k + 2] - SYNC_RGB[2]) < 40)
        if hits > 0.8 * w * h:
            first = i if first is None else first
        elif first is not None:
            return first / fps, i / fps
    return (first / fps, first / fps + 0.5) if first is not None else None


GW, GH, GFPS = 96, 60, 10  # alignment raster: grey 96x60 at 10 fps


def grey_frames(video):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={GFPS},scale={GW}:{GH},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    size = GW * GH
    return [p.stdout[i * size:(i + 1) * size] for i in range(len(p.stdout) // size)]


def grey_image(png):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf", f"scale={GW}:{GH},format=gray",
                           "-f", "rawvideo", "-"], capture_output=True).stdout


def mad(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def align_steps(steps, shots_dir, frames, lag, t_min, vdur):
    """Per-step [start, end] in video seconds.

    Playwright's screencast falls behind the wall clock while pages load (about 1-2 s by the end
    of a 40 s run here), so wall-clock offsets alone cut each step early. Each step's screenshot
    is taken at its end: find where the video shows that picture, and end the segment when the
    video stops showing it (the next step has started). Steps are contiguous: each starts where
    the previous one ended. Falls back to the offsets plus the drift seen so far when a
    screenshot has no clear match."""
    out, prev_end, drift = [], None, 0.0
    for s in steps:
        exp_start, exp_end = lag + s["startMs"] / 1000, lag + s["endMs"] / 1000
        start = max(t_min, exp_start if prev_end is None else prev_end)
        how = "clock"
        end = min(vdur, exp_end + drift)
        shot = shots_dir / s["screenshot"] if s.get("screenshot") else None
        if shot and shot.exists() and frames:
            ref = grey_image(shot)
            lo, hi = int(start * GFPS), min(len(frames), int((exp_end + drift + 6) * GFPS) + 1)
            diffs = [(i, mad(frames[i], ref)) for i in range(lo, hi)]
            if diffs:
                best = min(d for _, d in diffs)
                if best < 10:
                    # Runs of frames showing the screenshot (1-frame gaps allowed); take the run
                    # nearest the expected end. Consecutive steps can end on the same screen, so
                    # "first match" would swallow the next step's opening.
                    runs, cur = [], None
                    for i, d in diffs:
                        if d <= best + 0.6:  # a dropdown opening is ~+1 on this raster
                            if cur and i - cur[1] <= 2:
                                cur[1] = i
                            else:
                                cur = [i, i]
                                runs.append(cur)
                    target = (exp_end + drift) * GFPS
                    r0, r1 = min(runs, key=lambda r: 0 if r[0] <= target <= r[1] else min(abs(r[0] - target), abs(r[1] - target)))
                    hit, run_end = r0 / GFPS, r1 / GFPS + 0.04  # end on the last matching frame
                    end = min(run_end, max(hit, exp_end + drift) + 1.5, vdur)
                    end = max(end, hit + 1 / GFPS)
                    how = f"screenshot match (diff {best:.1f})"
        end = max(end, start + 0.2)
        drift = end - exp_end
        out.append((start, end, how))
        prev_end = end
    return out


def tts(text, out_wav, a):
    """Voice one step with narrated-deck's tts.py; cache by text+voice+model."""
    key = hashlib.sha256(f"{a.voice}|{a.model}|{a.style}|{text}".encode()).hexdigest()[:16]
    stamp = out_wav.with_suffix(".key")
    if out_wav.exists() and stamp.exists() and stamp.read_text() == key:
        return
    txt = out_wav.with_suffix(".txt")
    txt.write_text(text + "\n")
    env = dict(os.environ)
    last = ""
    for model in (a.model, a.model, "flash"):
        r = subprocess.run([sys.executable, str(a.tts), "-f", str(txt), "--voice", a.voice, "--model", model,
                            "--style", a.style, "-o", str(out_wav)], capture_output=True, text=True, env=env)
        if r.returncode == 0 and out_wav.exists():
            stamp.write_text(key)
            print("  " + r.stdout.strip())
            return
        last = (r.stderr or r.stdout).strip()[-300:]
        print(f"  tts retry ({model}): {last[:160]}", file=sys.stderr)
    sys.exit(f"TTS failed for {out_wav.name}: {last}")


def enc_args(a):
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf), "-maxrate", "2400k", "-bufsize", "4800k",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
            "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "1"]


def text_file(work, name, text):
    p = work / "txt" / name
    p.write_text(text)
    return p


def caption_filters(W, H, work, n, total, name, status, tag, speed_note):
    bar = int(H * 0.085)
    fs_small, fs_name = int(H * 0.022), int(H * 0.03)
    y_bar = H - bar
    pad = int(W * 0.018)
    status_color = {"pass": "0x34D399", "fail": "0xF87171"}.get(status, "0xFBBF24")
    left = text_file(work, f"cap-{n:02d}-step.txt", f"STEP {n} OF {total}")
    title = text_file(work, f"cap-{n:02d}-name.txt", name if len(name) <= 90 else name[:87] + "...")
    stat = text_file(work, f"cap-{n:02d}-status.txt", status.upper())
    right = text_file(work, f"cap-{n:02d}-tag.txt", tag + (f"  ·  {speed_note}" if speed_note else ""))
    common = "expansion=none:fix_bounds=1"
    return [
        f"drawbox=x=0:y={y_bar}:w=iw:h={bar}:color=0x0F172A@0.86:t=fill",
        f"drawtext=fontfile={esc(FONT_BOLD)}:textfile={esc(left)}:{common}:fontsize={fs_small}:fontcolor=0xA5B4FC:x={pad}:y={y_bar}+{int(bar*0.16)}",
        f"drawtext=fontfile={esc(FONT_BOLD)}:textfile={esc(stat)}:{common}:fontsize={fs_small}:fontcolor={status_color}:x={pad}+{int(fs_small*7.6)}:y={y_bar}+{int(bar*0.16)}",
        f"drawtext=fontfile={esc(FONT)}:textfile={esc(title)}:{common}:fontsize={fs_name}:fontcolor=white:x={pad}:y={y_bar}+{int(bar*0.46)}",
        f"drawtext=fontfile={esc(FONT)}:textfile={esc(right)}:{common}:fontsize={fs_small}:fontcolor=0xCBD5E1:x=w-tw-{pad}:y={y_bar}+{int(bar*0.16)}",
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--steps", required=True)
    ap.add_argument("--narration", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--date", help="caption date tag (default: steps.json run date)")
    ap.add_argument("--env", default="stage")
    ap.add_argument("--voice", default="Charon")
    ap.add_argument("--model", default="pro", help="pro | flash | next (tts.py aliases)")
    ap.add_argument("--style", default=DEFAULT_STYLE)
    ap.add_argument("--tts", help="path to narrated-deck's assets/tts.py (see the docstring for the lookup order)")
    ap.add_argument("--lead-ms", type=int, help="video time (ms) at test start; overrides sync flash / videoLeadMs")
    ap.add_argument("--speedup-over", type=float, default=20.0, help="speed up real steps longer than this (s)")
    ap.add_argument("--crf", type=int, default=26)
    ap.add_argument("--work", help="work dir (default <out dir>/walkthrough-work)")
    ap.add_argument("--html", help="HTML path (default <out dir>/walkthrough.html)")
    ap.add_argument("--no-align", action="store_true", help="cut on the recorded offsets only (no screenshot matching)")
    ap.add_argument("--no-tts", action="store_true", help="silent segments (layout check without Gemini)")
    a = ap.parse_args()
    a.tts, tts_from = resolve_tts(a.tts)

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not on PATH")
    video, steps_path, out = pathlib.Path(a.video).resolve(), pathlib.Path(a.steps).resolve(), pathlib.Path(a.out).resolve()
    report = json.loads(steps_path.read_text())
    steps = report["steps"]
    shots_dir = steps_path.parent
    narr = parse_narration(pathlib.Path(a.narration).read_text())
    run_date = a.date or (report.get("testStartedAt") or report.get("ranAt") or "")[:10] or datetime.date.today().isoformat()
    tag = f"{a.env} · {run_date}"
    shown = [s for s in steps if s["status"] != "skip"]
    missing = [s["n"] for s in shown if s["n"] not in narr]
    if missing:
        sys.exit(f"narration.md has no '## Step N' section for step(s) {missing}")
    for s in shown:
        wc = len(narr[s["n"]].split())
        if wc < 30 or wc > 60:
            print(f"note: step {s['n']} narration is {wc} words (aim 30-60)")
    if "startMs" not in steps[0]:
        sys.exit("steps.json has no startMs/endMs: record it with the walk.ts step recorder")

    out.parent.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(a.work).resolve() if a.work else out.parent / "walkthrough-work"
    for sub in ("audio", "seg", "txt"):
        (work / sub).mkdir(parents=True, exist_ok=True)

    vw, vh, vdur = probe(video)
    scale = min(MAX_W / vw, MAX_H / vh, 1.0)
    W, H = int(vw * scale) // 2 * 2, int(vh * scale) // 2 * 2
    flash = find_sync_flash(video) if report.get("syncMarkMs") is not None else None
    t_min = flash[1] + 0.04 if flash else 0.0
    if a.lead_ms is not None:
        lag, how = a.lead_ms / 1000, "--lead-ms"
    elif flash:
        lag, how = flash[0] - report["syncMarkMs"] / 1000, f"sync flash at {flash[0]:.2f}s"
    else:
        lag, how = report.get("videoLeadMs", 0) / 1000, "videoLeadMs (no sync flash)"
    print(f"video {vw}x{vh} {vdur:.1f}s -> {W}x{H}; step offsets + {lag:.2f}s ({how})")

    spans = align_steps(shown, shots_dir, [] if a.no_align else grey_frames(video), lag, t_min, vdur)

    # 1. narration
    if not a.no_tts:
        if not a.tts.exists():
            sys.exit(f"tts.py not found at {a.tts} (from {tts_from}); install the narrated-deck plugin and set "
                     f"tts.narrated_deck_dir in feature-workflow.json, or pass --tts, or use --no-tts")
        print(f"TTS ({a.voice}, {a.model}) for {len(shown)} steps")
    for s in shown:
        if not a.no_tts:
            tts(narr[s["n"]], work / "audio" / f"step-{s['n']:02d}.wav", a)

    segs, timeline = [], []
    t_cursor = TITLE_SEC
    fit = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1"

    # 2. title card
    title_seg = work / "seg" / "00-title.mp4"
    tfile = text_file(work, "title.txt", a.title)
    passed = sum(1 for s in shown if s["status"] == "pass")
    sub = text_file(work, "subtitle.txt", f"Gate B walkthrough  ·  {len(shown)} steps  ·  {passed} passed  ·  recorded on {a.env}")
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x0F172A:s={W}x{H}:d={TITLE_SEC}:r={FPS}",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(TITLE_SEC),
         "-vf", ",".join([
             f"drawtext=fontfile={esc(FONT_BOLD)}:textfile={esc(tfile)}:expansion=none:fontsize={int(H*0.055)}:fontcolor=white:x=(w-tw)/2:y=h*0.42",
             f"drawtext=fontfile={esc(FONT)}:textfile={esc(sub)}:expansion=none:fontsize={int(H*0.026)}:fontcolor=0xA5B4FC:x=(w-tw)/2:y=h*0.42+{int(H*0.09)}"]),
         *enc_args(a), str(title_seg)])
    segs.append(title_seg)

    # 3. step segments
    for s in shown:
        n = s["n"]
        start, end, align_how = spans[shown.index(s)]
        real = max(0.04, end - start)
        wav = work / "audio" / f"step-{n:02d}.wav"
        narr_sec = wav_seconds(wav) if (not a.no_tts and wav.exists()) else 3.0
        speed = 1.0
        target = max(narr_sec + PAUSE, real)
        if real > a.speedup_over and real > narr_sec + PAUSE:
            target = max(narr_sec + PAUSE, a.speedup_over)
            speed = real / target
        play = real / speed
        hold = max(0.0, target - play)
        note = f"{speed:.1f}× speed" if speed > 1.05 else ""
        vf = [f"setpts=(PTS-STARTPTS)/{speed:.4f}", f"fps={FPS}", fit,
              f"tpad=stop_mode=clone:stop_duration={hold + 0.2:.3f}", f"trim=duration={target:.3f}", "setpts=PTS-STARTPTS"]
        vf += caption_filters(W, H, work, n, len(shown), s["name"], s["status"], tag, note)
        seg = work / "seg" / f"{n:02d}.mp4"
        audio_in = ["-i", str(wav)] if (not a.no_tts and wav.exists()) else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{real:.3f}", "-i", str(video), *audio_in,
             "-filter_complex", f"[0:v]{','.join(vf)}[v];[1:a]aresample=44100,aformat=channel_layouts=mono,apad,atrim=duration={target:.3f}[a]",
             "-map", "[v]", "-map", "[a]", "-t", f"{target:.3f}", *enc_args(a), str(seg)])
        segs.append(seg)
        timeline.append({"n": n, "t": round(t_cursor, 2), "duration": round(target, 2), "real": round(real, 2),
                         "narration_sec": round(narr_sec, 2), "speed": round(speed, 2),
                         "video_start": round(start, 2), "video_end": round(end, 2), "aligned_by": align_how})
        print(f"  step {n}: video {start:.1f}-{end:.1f}s ({real:.1f}s, {align_how}), narration {narr_sec:.1f}s -> {target:.1f}s{' ' + note if note else ''}")
        t_cursor += target

    # 4. end card
    end_seg = work / "seg" / "99-end.mp4"
    lines = len(shown)
    fs = int(min(H * 0.032, (H * 0.72) / max(1, lines) / 1.45))
    y0 = int((H - lines * fs * 1.45) / 2) + int(H * 0.04)
    draws = [f"drawtext=fontfile={esc(FONT_BOLD)}:textfile={esc(text_file(work, 'end-head.txt', 'Result on ' + tag))}:expansion=none:fontsize={int(fs*1.15)}:fontcolor=white:x=w*0.12:y={y0 - int(fs*2.4)}"]
    for i, s in enumerate(shown):
        y = y0 + int(i * fs * 1.45)
        col = {"pass": "0x34D399", "fail": "0xF87171"}.get(s["status"], "0xFBBF24")
        st = text_file(work, f"end-{s['n']:02d}-st.txt", s["status"].upper())
        nm = text_file(work, f"end-{s['n']:02d}-nm.txt", f"{s['n']}.  {s['name'][:80]}")
        draws.append(f"drawtext=fontfile={esc(FONT_BOLD)}:textfile={esc(st)}:expansion=none:fontsize={fs}:fontcolor={col}:x=w*0.12:y={y}")
        draws.append(f"drawtext=fontfile={esc(FONT)}:textfile={esc(nm)}:expansion=none:fontsize={fs}:fontcolor=0xE2E8F0:x=w*0.12+{int(fs*4.2)}:y={y}")
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x0F172A:s={W}x{H}:d={END_SEC}:r={FPS}",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(END_SEC), "-vf", ",".join(draws), *enc_args(a), str(end_seg)])
    segs.append(end_seg)

    # 5. concat
    lst = work / "seg" / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in segs))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)])
    _, _, total = probe(out)
    mb = out.stat().st_size / 1e6
    print(f"{out}  {W}x{H}  {int(total // 60)}:{int(total % 60):02d}  {mb:.1f} MB")
    if mb > 60 * max(1.0, total / 180):
        print(f"warning: {mb:.1f} MB is over the 60 MB / 3 min budget; raise --crf", file=sys.stderr)

    # 6. HTML
    html_path = pathlib.Path(a.html).resolve() if a.html else out.parent / "walkthrough.html"
    write_html(html_path, out, a.title, tag, shown, narr, timeline, shots_dir, total)
    (work / "timeline.json").write_text(json.dumps({"lag_sec": round(lag, 3), "lag_source": how, "duration_sec": round(total, 2),
                                                     "size_mb": round(mb, 2), "steps": timeline}, indent=2))
    print(f"{html_path}")


def write_html(path, mp4, title, tag, shown, narr, timeline, shots_dir, total):
    shots = {s["n"]: shots_dir / s["screenshot"] for s in shown if s.get("screenshot") and (shots_dir / s["screenshot"]).exists()}
    inline = sum(p.stat().st_size for p in shots.values()) * 4 / 3 + 200_000 < HTML_BUDGET
    tl = {t["n"]: t for t in timeline}
    passed = sum(1 for s in shown if s["status"] == "pass")
    failed = sum(1 for s in shown if s["status"] == "fail")
    feature = re.split(r"\s+on\s+|,", title)[0].strip()
    mp4_rel = os.path.relpath(mp4, path.parent)
    poster = ""
    if shown and shown[0]["n"] in shots:
        f = shots[shown[0]["n"]]
        poster = ("data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()) if inline else html.escape(os.path.relpath(f, path.parent))
    rows = []
    for s in shown:
        n, t = s["n"], tl.get(s["n"], {"t": 0})
        img = ""
        if n in shots:
            src = ("data:image/png;base64," + base64.b64encode(shots[n].read_bytes()).decode()) if inline \
                else html.escape(os.path.relpath(shots[n], path.parent))
            img = f'<details class="shot"><summary>Screenshot at the end of the step</summary><img src="{src}" alt="Step {n}: {html.escape(s["name"])}" loading="lazy"></details>'
        err = f'<p class="err">{html.escape(s["error"])}</p>' if s.get("error") else ""
        rows.append(f'''<li class="step {s["status"]}">
  <div class="head"><button class="tc" type="button" data-t="{t["t"]}" aria-label="Play step {n} from {t["t"]:.0f} seconds">{int(t["t"]//60)}:{int(t["t"]%60):02d}</button>
  <span class="pill {s["status"]}">{s["status"].upper()}</span><h3><span class="num">{n}</span> {html.escape(s["name"])}</h3></div>
  <p class="narr">{html.escape(narr.get(n, ""))}</p>{err}{img}
</li>''')
    doc = f'''<title>{html.escape(feature)} walkthrough</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap">
<style>
:root {{ --bg:#F4F6F9; --surface:#FFFFFF; --ink:#141821; --muted:#5A6272; --line:#DCE1E8; --accent:#3F51D6;
  --pass:#0E7A5A; --pass-bg:#E3F4EC; --fail:#B42A25; --fail-bg:#FBE7E5; --skip:#8A5A00; --skip-bg:#FDF0D8; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark;
  --bg:#0E1117; --surface:#161B24; --ink:#E6E9EF; --muted:#9AA3B2; --line:#2A3140; --accent:#8C9BFF;
  --pass:#4ADE9B; --pass-bg:#10281F; --fail:#FF8A80; --fail-bg:#321816; --skip:#F5C451; --skip-bg:#2E2412; }} }}
:root[data-theme="dark"] {{ color-scheme: dark;
  --bg:#0E1117; --surface:#161B24; --ink:#E6E9EF; --muted:#9AA3B2; --line:#2A3140; --accent:#8C9BFF;
  --pass:#4ADE9B; --pass-bg:#10281F; --fail:#FF8A80; --fail-bg:#321816; --skip:#F5C451; --skip-bg:#2E2412; }}
body {{ background:var(--bg); color:var(--ink); font:16px/1.55 "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif; }}
.wrap {{ max-width:960px; margin:0 auto; padding-inline:16px; padding-block:28px 48px; display:grid; gap:22px; }}
.eyebrow {{ font:500 12px/1 "IBM Plex Mono", ui-monospace, monospace; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:0; }}
h1 {{ font-size:clamp(24px, 4vw, 34px); line-height:1.15; margin:6px 0 0; text-wrap:balance; font-weight:600; }}
.summary {{ display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; color:var(--muted); font-size:14px; }}
.summary strong {{ color:var(--ink); font-weight:600; }}
video {{ width:100%; max-width:100%; aspect-ratio:16/10; background:#0F172A; border-radius:8px; border:1px solid var(--line); display:block; }}
.dl a {{ color:var(--accent); font-weight:500; }}
ol {{ list-style:none; margin:0; padding:0; display:grid; gap:12px; }}
.step {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px 16px; display:grid; gap:8px; }}
.step.fail {{ border-color:var(--fail); }}
.head {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px; }}
h3 {{ margin:0; font-size:17px; font-weight:600; flex:1 1 260px; text-wrap:balance; }}
.num {{ font-family:"IBM Plex Mono", ui-monospace, monospace; color:var(--muted); font-weight:500; margin-right:4px; }}
.tc {{ font:500 13px/1 "IBM Plex Mono", ui-monospace, monospace; font-variant-numeric:tabular-nums; color:var(--accent);
  background:transparent; border:1px solid var(--line); border-radius:6px; padding:6px 8px; cursor:pointer; }}
.tc:hover, .tc:focus-visible {{ border-color:var(--accent); outline:none; }}
.pill {{ font:500 12px/1 "IBM Plex Mono", ui-monospace, monospace; letter-spacing:.06em; padding:5px 8px; border-radius:999px; }}
.pill.pass {{ color:var(--pass); background:var(--pass-bg); }} .pill.fail {{ color:var(--fail); background:var(--fail-bg); }}
.pill.skip {{ color:var(--skip); background:var(--skip-bg); }}
.narr {{ margin:0; color:var(--ink); max-width:68ch; }}
.err {{ margin:0; color:var(--fail); font:13px/1.45 "IBM Plex Mono", ui-monospace, monospace; white-space:pre-wrap; overflow-wrap:anywhere; }}
.shot summary {{ cursor:pointer; color:var(--muted); font-size:14px; }}
.shot img {{ margin-top:8px; border:1px solid var(--line); border-radius:6px; max-width:100%; height:auto; }}
footer {{ color:var(--muted); font-size:13px; }}
@media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior:auto !important; }} }}
</style>
<main class="wrap">
  <header><p class="eyebrow">Gate B · {html.escape(tag)}</p><h1>{html.escape(title)}</h1></header>
  <div class="summary"><span><strong>{passed}</strong> of {len(shown)} steps passed</span>{f'<span><strong>{failed}</strong> failed</span>' if failed else ''}<span>{int(total//60)}:{int(total%60):02d} narrated video</span></div>
  <video id="v" controls preload="metadata" playsinline src="{html.escape(mp4_rel)}"{f' poster="{poster}"' if poster else ""}></video>
  <p class="dl">Video file: <a href="{html.escape(mp4_rel)}">{html.escape(os.path.basename(mp4_rel))}</a>. Timecodes below jump to each step.</p>
  <ol>{"".join(rows)}</ol>
  <footer>Recorded by Playwright on the {html.escape(tag.split(" · ")[0])} tier; each step's result comes from the assertions in the walkthrough spec, not from the narration.</footer>
</main>
<script>
document.querySelectorAll('.tc').forEach(function (b) {{
  b.addEventListener('click', function () {{
    var v = document.getElementById('v');
    try {{ v.currentTime = parseFloat(b.dataset.t); v.play().catch(function () {{}}); v.scrollIntoView({{block: 'nearest'}}); }} catch (e) {{}}
  }});
}});
</script>
'''
    path.write_text(doc)
    print(f"html: {path.stat().st_size / 1e6:.2f} MB, screenshots {'inlined' if inline else 'linked'}")


if __name__ == "__main__":
    main()
