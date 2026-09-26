# Gate B walkthrough

A two-to-three-minute narrated screen recording of a feature running on the stage tier, so the
founder can approve a release by watching instead of reading. It sits beside `uat.md` at Gate B
the way the narrated deck sits beside `plan.md` at Gate A.

```
your app repo                                    this directory
uat/walkthrough/<slug>.walkthrough.spec.ts  ──▶  build-walkthrough.py  ──▶  <feature>/uat/
   (Playwright, video on, walk.ts steps)           (TTS + ffmpeg)            walkthrough.mp4
   <outputDir>/<test>/video.webm                                             walkthrough.html
   <WALK_REPORT_DIR>/steps.json + NN-*.png
```

## 0. One-time setup in the app repo

Copy `walk.ts` from this directory into the app repo (e.g. `uat/walkthrough/walk.ts`) and add a
Playwright config that records one long test with video:

```ts
// uat/playwright.walkthrough.config.ts
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './walkthrough',
  globalSetup: './global-setup',          // your stage sign-in (storageState, token minting, ...)
  timeout: 30 * 60_000, workers: 1, retries: 0,
  outputDir: 'walkthrough-results',
  use: {
    baseURL: process.env.UAT_BASE_URL,
    video: { mode: 'on', size: { width: 1440, height: 900 } },
    viewport: { width: 1440, height: 900 },
  },
});
```

A spec looks like this (one `step()` per acceptance case, step names in the founder's words):

```ts
import { test, expect } from '@playwright/test';
import { startWalk, step, finishWalk } from './walk';

test('order history walkthrough', async ({ page }) => {
  await page.goto('/');
  await startWalk({ feature: 'order-history' }, page);   // paints the sync flash
  await step(page, 'A customer sees their last ten orders', async (d) => {
    await page.goto('/orders');
    await expect(page.getByTestId('orders-table')).toBeVisible();
    d.push('10 rows');
  });
  await step(page, 'A viewer cannot export orders', async () => { /* ... */ });
  finishWalk({ baseURL: process.env.UAT_BASE_URL });
});
```

## 1. Record on stage

```bash
cd <app repo>
UAT_BASE_URL=<stage url> WALK_REPORT_DIR=uat/walkthrough/report-<slug> \
npx playwright test --config=uat/playwright.walkthrough.config.ts uat/walkthrough/<slug>.walkthrough.spec.ts
```

Use a stage account that owns nothing for the denied steps and a separate one for any
admin-only steps. Copy the run out of the repo before re-running (the next run overwrites it):
`<feature>/uat/walkthrough-run/` = `steps.json`, the step PNGs and `video.webm`.
`WALK_STEPS=1,3` re-records only those steps (the others are recorded as skip).

## 2. Write the narration

`<feature>/uat/narration.md`: a `## Step N` section per step, 30-60 words each, in the
founder's words: what they are looking at and why it matters, with the real numbers from
`steps.json` details. Say "simulated" when a step mocks a balance or a record. No code terms.

## 3. Build

```bash
python3 build-walkthrough.py --video walkthrough-run/video.webm --steps walkthrough-run/steps.json \
  --narration narration.md --out <feature>/uat/walkthrough.mp4 --title "<Feature> on stage, <date>"
```

Options: `--voice` (Charon), `--model` (pro, falls back to flash), `--speedup-over 20` (a real step
longer than this plays faster, and the caption says so), `--lead-ms` (manual offset), `--no-align`,
`--no-tts` (silent layout check), `--work` (default `<out dir>/walkthrough-work`: TTS cache and
segments; put it in a scratch dir to keep the feature folder clean), `--tts` (path to
narrated-deck's `assets/tts.py`; otherwise `$NARRATED_DECK_TTS`, then `tts.narrated_deck_dir` in
`feature-workflow.json`, then `~/.claude/skills/narrated-deck/assets/tts.py`).

What it does: Gemini TTS per step through the narrated-deck skill's `tts.py` (cached by text, so
editing one section re-voices one step); lines the video up with the sync flash, then refines each
step's end by finding its end-of-step screenshot in the video (Playwright's screencast drifts
1-3 s behind the wall clock while pages load, so offsets alone cut into the next step); each step
lasts max(narration + 0.6 s, real time), holding its last frame; caption strip with step number,
PASS/FAIL, name and `stage · <date>`; 1.5 s title card and 2 s PASS/FAIL end card; H.264 yuv420p
≤1440x900, AAC mono, bitrate capped at 2.4 Mb/s (well under 60 MB for 3 minutes).

`walkthrough.html` lands next to the MP4: title, video (poster = first step), per-step timecode
buttons, status, narration and the end-of-step screenshot (inlined while the page stays under
12 MB, else relative paths). `walkthrough-work/timeline.json` records how each step was aligned.

## 4. Publish and link

Publish `walkthrough.html` wherever the founder reads things (in Claude Code, the Artifact tool
with the MP4 as a supporting file so the player works; above the size limit, link a cloud-drive
copy instead). Add `"walkthrough": {"mp4": "...", "url": "..."}` to the feature's `links.json` and
show the link at Gate B next to `uat.md`.

Check before sending: the freeze frame of each step shows the state the narration describes (the
build prints the video span per step), and no step says PASS in the narration that failed in
`steps.json`. Stage data can show real account emails in the UI; they end up in the video.

Needs: python3 (stdlib), ffmpeg/ffprobe, DejaVu fonts (or `WALKTHROUGH_FONT` /
`WALKTHROUGH_FONT_BOLD`), the narrated-deck skill's `tts.py` and its Gemini key.
