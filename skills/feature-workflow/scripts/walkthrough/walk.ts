/**
 * Step recorder for recorded Gate B walkthroughs. Copy this file into your app repo next to the
 * walkthrough specs (e.g. uat/walkthrough/walk.ts) and run the specs with a Playwright config
 * that records video (see README.md in this directory).
 *
 * step(page, name, fn) runs one acceptance step, never throws (a failed step is
 * recorded and the walk continues), logs `[step N] PASS name (ms)`, saves a
 * screenshot per step into the report dir, and rewrites report/steps.json after
 * every step so a walk that dies half way still leaves a usable record.
 *
 * steps.json carries, per step, start/end offsets in ms relative to the test
 * start, plus `videoLeadMs` (how long the Playwright video had been running
 * when the test started: the fixture opens the page and signs in first). The
 * Gate B build tool (feature-workflow skill, scripts/walkthrough/build-walkthrough.py)
 * cuts the .webm with
 * `videoLeadMs + startMs .. videoLeadMs + endMs`.
 *
 * Env: WALK_REPORT_DIR (default uat/walkthrough/report), WALK_STEPS=1,3,5 runs
 * only those step numbers (the others are recorded as skip).
 */
import type { Page } from 'playwright/test';
import fs from 'fs';
import path from 'path';

export type WalkStep = {
  n: number;
  name: string;
  status: 'pass' | 'fail' | 'skip';
  details: string[];
  error?: string;
  screenshot?: string;
  /** Duration of fn() alone (the number in the log line). */
  ms: number;
  /** Offset from the test start when the step began, ms. */
  startMs: number;
  /** Offset from the test start when the step ended (after its screenshot), ms. */
  endMs: number;
};

/**
 * Set this from your `page` fixture the moment the recorded page exists
 * (`videoClock.pageOpenedAt = Date.now()`), so steps.json can carry videoLeadMs as a fallback
 * when the spec does not call startWalk(meta, page).
 */
export const videoClock = { pageOpenedAt: 0 };

export const REPORT_DIR = process.env.WALK_REPORT_DIR || path.join(__dirname, 'report');
const ONLY = (process.env.WALK_STEPS || '')
  .split(',')
  .map((x) => x.trim())
  .filter(Boolean)
  .map(Number);

const steps: WalkStep[] = [];
let stepNo = 0;
let testStartedAt = 0;
let meta: Record<string, unknown> = {};

/** Colour of the sync flash; build-walkthrough.py looks for it in the video. */
export const SYNC_COLOR = '#ff00ff';

/**
 * Mark the test start (call first thing in the test). Implicit on the first
 * step otherwise. Pass the recorded page to also paint a 0.4 s full-screen
 * magenta sync flash: its offset is written as `syncMarkMs`, and the build tool
 * finds the flash in the video to line the step offsets up to the frame
 * (Playwright's video starts a second or two before the fixture hands over the
 * page, so `videoLeadMs` alone is only a fallback).
 */
export async function startWalk(extra: Record<string, unknown> = {}, page?: Page) {
  testStartedAt = Date.now();
  meta = { ...meta, ...extra };
  fs.mkdirSync(REPORT_DIR, { recursive: true });
  if (!page) return;
  try {
    await page.evaluate((color) => {
      const el = document.createElement('div');
      el.id = '__walk_sync';
      el.style.cssText = `position:fixed;inset:0;z-index:2147483647;background:${color}`;
      document.documentElement.appendChild(el);
      return new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    }, SYNC_COLOR);
    meta.syncMarkMs = Date.now() - testStartedAt;
    await page.waitForTimeout(400);
    await page.evaluate(() => document.getElementById('__walk_sync')?.remove());
  } catch {}
}

function writeSteps(extra: Record<string, unknown> = {}) {
  meta = { ...meta, ...extra };
  const videoLeadMs = videoClock.pageOpenedAt ? Math.max(0, testStartedAt - videoClock.pageOpenedAt) : 0;
  fs.mkdirSync(REPORT_DIR, { recursive: true });
  fs.writeFileSync(
    path.join(REPORT_DIR, 'steps.json'),
    JSON.stringify(
      { ranAt: new Date().toISOString(), ...meta, testStartedAt: new Date(testStartedAt).toISOString(), videoLeadMs, steps },
      null,
      2,
    ),
  );
}

export async function step(page: Page, name: string, fn: (d: string[]) => Promise<void>) {
  if (!testStartedAt) startWalk();
  const n = ++stepNo;
  const details: string[] = [];
  const t0 = Date.now();
  const rec: WalkStep = { n, name, status: 'pass', details, ms: 0, startMs: t0 - testStartedAt, endMs: t0 - testStartedAt };
  if (ONLY.length && !ONLY.includes(n)) {
    rec.status = 'skip';
    steps.push(rec);
    writeSteps();
    console.log(`[step ${n}] SKIP ${name}`);
    return;
  }
  try {
    await fn(details);
  } catch (e) {
    rec.status = 'fail';
    rec.error = (e instanceof Error ? e.message : String(e)).split('\n').slice(0, 6).join('\n');
  }
  rec.ms = Date.now() - t0;
  try {
    const file = `${String(n).padStart(2, '0')}-${name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.png`;
    await page.screenshot({ path: path.join(REPORT_DIR, file) });
    rec.screenshot = file;
  } catch {}
  rec.endMs = Date.now() - testStartedAt;
  steps.push(rec);
  writeSteps();
  console.log(`[step ${n}] ${rec.status.toUpperCase()} ${name} (${rec.ms}ms)${rec.error ? ' :: ' + rec.error.split('\n')[0] : ''}`);
}

/** Final write (extra top-level fields, e.g. baseURL) and the `N/M steps passed` line. */
export function finishWalk(extra: Record<string, unknown> = {}, label = 'walkthrough') {
  writeSteps(extra);
  console.log(`[${label}] ${steps.filter((s) => s.status === 'pass').length}/${steps.length} steps passed`);
  return steps;
}
