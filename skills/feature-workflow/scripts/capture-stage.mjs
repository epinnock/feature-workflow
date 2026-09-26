#!/usr/bin/env node
/**
 * Full-page screenshot of one page on your stage dashboard, in a given signed-in state, for
 * figma-vs-stage.py. It never drives a sign-in UI. Two ways to be signed in:
 *
 *  - storage state (any auth stack): a Playwright storageState JSON saved by your UAT setup,
 *    passed with --storage-state or set as dashboard.auth.storage_state in feature-workflow.json.
 *  - Firebase custom token (dashboard.auth.mode = "firebase-custom-token"): firebase-admin with a
 *    stage service account mints a custom token for --uid, the page signs in with
 *    signInWithCustomToken (Firebase web SDK from the gstatic CDN), and the script waits until
 *    Firebase persistence has landed before opening the target page.
 *
 * Usage:
 *   node capture-stage.mjs --path /orders --out shots/orders-list-loaded.png \
 *     [--uid <stage uid> | --signed-out | --storage-state state.json] \
 *     [--width 1440] [--height 1024] [--wait-testid orders-table] [--wait-selector css] \
 *     [--wait-text "No orders yet"] [--settle 4000] [--viewport-only]
 *
 * Config (feature-workflow.json, found in the current directory or a parent, or at
 * $FEATURE_WORKFLOW_CONFIG):
 *   dashboard.stage_url            base URL of the stage dashboard (UAT_BASE_URL overrides it)
 *   dashboard.repo                 a checkout with node_modules (playwright, and firebase-admin
 *                                  for the Firebase mode); relative to the ops root
 *   dashboard.stage_host_pattern   regex the base URL must match (default: the stage_url host,
 *                                  localhost or 127.0.0.1); production is refused
 *   dashboard.login_path           page opened before the Firebase sign-in (default /login)
 *   dashboard.auth.mode            "firebase-custom-token" | "storage-state" | "none"
 *   dashboard.auth.storage_state   storageState JSON path (storage-state mode)
 *   dashboard.auth.service_account stage service-account JSON path, inside dashboard.repo
 *   dashboard.auth.env_file        env file with NEXT_PUBLIC_FIREBASE_* keys, inside dashboard.repo
 *   dashboard.auth.default_uid     uid used when --uid is not given
 * Nothing secret is printed. Width = the Figma frame's width; state = the frame's state.
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

function die(msg) {
  console.error(`capture-stage: ${msg}`);
  process.exit(3);
}

function findConfig() {
  if (process.env.FEATURE_WORKFLOW_CONFIG) return path.resolve(process.env.FEATURE_WORKFLOW_CONFIG);
  let d = process.cwd();
  for (;;) {
    const p = path.join(d, 'feature-workflow.json');
    if (fs.existsSync(p)) return p;
    const up = path.dirname(d);
    if (up === d) return null;
    d = up;
  }
}
const CONFIG_PATH = findConfig();
if (!CONFIG_PATH) die('no feature-workflow.json in this directory or a parent (or set FEATURE_WORKFLOW_CONFIG)');
const CONFIG = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
const OPS_ROOT = path.dirname(CONFIG_PATH);
const get = (key) => key.split('.').reduce((o, k) => (o && o[k] !== undefined && o[k] !== '' ? o[k] : undefined), CONFIG);
const need = (key, why) => {
  const v = get(key);
  if (v === undefined) die(`${CONFIG_PATH}: missing key '${key}' (${why}); see scripts/README.md`);
  return v;
};
const resolveFrom = (base, p) => (path.isAbsolute(p) ? p : path.join(base, p.replace(/^~(?=\/)/, process.env.HOME || '~')));

const BASE = (process.env.UAT_BASE_URL || need('dashboard.stage_url', 'the stage dashboard URL')).replace(/\/+$/, '');
const REPO = resolveFrom(OPS_ROOT, need('dashboard.repo', 'a dashboard checkout with playwright installed'));
const CDN = 'https://www.gstatic.com/firebasejs/12.4.0';
const auth = get('dashboard.auth') || {};

const opts = { width: 1440, height: 1024, settle: 4000, uid: auth.default_uid };
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const k = argv[i].replace(/^--/, '');
  if (k === 'signed-out' || k === 'viewport-only') { opts[k] = true; continue; }
  opts[k] = argv[++i];
}
if (!opts.path || !opts.out) {
  console.error('usage: capture-stage.mjs --path /route --out file.png [--uid uid|--signed-out|--storage-state f.json] [--width 1440] ...');
  process.exit(2);
}

const stageHost = new URL(get('dashboard.stage_url') || BASE).host.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const hostRx = new RegExp(get('dashboard.stage_host_pattern') || `^https?://(${stageHost}|localhost|127\\.0\\.0\\.1)(:\\d+)?$`);
if (!hostRx.test(BASE)) die(`refusing ${BASE}: it does not match dashboard.stage_host_pattern (stage or preview only)`);

const require = createRequire(path.join(REPO, 'package.json'));
let chromium;
try { ({ chromium } = require('playwright')); } catch { die(`playwright is not installed in ${REPO} (dashboard.repo)`); }

const mode = opts['signed-out'] ? 'none' : opts['storage-state'] ? 'storage-state' : (auth.mode || 'none');

function envFile(key) {
  const file = resolveFrom(REPO, need('dashboard.auth.env_file', 'env file with the Firebase web config'));
  const env = fs.readFileSync(file, 'utf8');
  const m = env.match(new RegExp(`^${key}=(.*)$`, 'm'));
  if (!m) die(`${key} not found in dashboard.auth.env_file`);
  let v = m[1].trim();
  if (v.startsWith('"') && v.endsWith('"')) v = JSON.parse(v);
  return v;
}

let session = null;
let storageState;
if (mode === 'firebase-custom-token') {
  if (!opts.uid) die('no --uid and no dashboard.auth.default_uid');
  let admin;
  try { admin = require('firebase-admin'); } catch { die(`firebase-admin is not installed in ${REPO}`); }
  const saPath = resolveFrom(REPO, need('dashboard.auth.service_account', 'stage service-account JSON'));
  const sa = JSON.parse(fs.readFileSync(saPath, 'utf8'));
  if (admin.apps.length === 0) admin.initializeApp({ credential: admin.credential.cert(sa) });
  session = {
    token: await admin.auth().createCustomToken(opts.uid),
    config: {
      apiKey: envFile('NEXT_PUBLIC_FIREBASE_API_KEY'),
      authDomain: envFile('NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN'),
      projectId: envFile('NEXT_PUBLIC_FIREBASE_PROJECT_ID'),
      appId: envFile('NEXT_PUBLIC_FIREBASE_APP_ID'),
    },
  };
} else if (mode === 'storage-state') {
  storageState = resolveFrom(OPS_ROOT, opts['storage-state'] || need('dashboard.auth.storage_state', 'Playwright storageState JSON'));
  if (!fs.existsSync(storageState)) die(`storage state file not found: ${storageState}`);
} else if (mode !== 'none') {
  die(`unknown dashboard.auth.mode '${mode}' (firebase-custom-token | storage-state | none)`);
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: Number(opts.width), height: Number(opts.height) }, storageState });
const page = await context.newPage();
if (session) {
  await page.goto(BASE + (get('dashboard.login_path') || '/login'), { waitUntil: 'domcontentloaded' });
  await page.evaluate(async ({ cdn, config, token }) => {
    const { initializeApp } = await import(/* webpackIgnore: true */ `${cdn}/firebase-app.js`);
    const { getAuth, signInWithCustomToken } = await import(/* webpackIgnore: true */ `${cdn}/firebase-auth.js`);
    const app = initializeApp(config);
    await signInWithCustomToken(getAuth(app), token);
    const key = `firebase:authUser:${config.apiKey}:[DEFAULT]`;
    for (let i = 0; i < 100; i++) {
      const found = await new Promise((resolve) => {
        const open = indexedDB.open('firebaseLocalStorageDb');
        open.onerror = () => resolve(false);
        open.onsuccess = () => {
          try {
            const get = open.result.transaction('firebaseLocalStorage', 'readonly').objectStore('firebaseLocalStorage').get(key);
            get.onsuccess = () => { const v = !!get.result; open.result.close(); resolve(v); };
            get.onerror = () => { open.result.close(); resolve(false); };
          } catch { open.result.close(); resolve(false); }
        };
      });
      if (found) return;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error('Firebase persistence never landed after sign-in');
  }, { cdn: CDN, config: session.config, token: session.token });
}
await page.goto(BASE + opts.path, { waitUntil: 'domcontentloaded' });
const waits = [];
if (opts['wait-testid']) waits.push(page.getByTestId(opts['wait-testid']).first().waitFor({ state: 'visible', timeout: 60_000 }));
if (opts['wait-selector']) waits.push(page.locator(opts['wait-selector']).first().waitFor({ state: 'attached', timeout: 60_000 }));
if (opts['wait-text']) waits.push(page.getByText(opts['wait-text']).first().waitFor({ state: 'visible', timeout: 60_000 }));
for (const w of waits) await w.catch((e) => console.warn('wait failed:', String(e.message || e).split('\n')[0]));
await page.waitForTimeout(Number(opts.settle));
if (!opts['viewport-only']) {
  // App shells often scroll inside <main>, not the document, so fullPage alone stops at the
  // viewport. Grow the viewport until the tallest inner scroller no longer scrolls.
  const extra = await page.evaluate(() => {
    let most = 0;
    for (const el of document.querySelectorAll('*')) {
      const oy = getComputedStyle(el).overflowY;
      if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 1) {
        most = Math.max(most, el.scrollHeight - el.clientHeight);
      }
    }
    return most;
  });
  if (extra > 0) {
    await page.setViewportSize({ width: Number(opts.width), height: Number(opts.height) + extra });
    await page.waitForTimeout(1500);
  }
}
fs.mkdirSync(path.dirname(path.resolve(opts.out)), { recursive: true });
await page.screenshot({ path: opts.out, fullPage: !opts['viewport-only'] });
const who = session ? opts.uid : storageState ? 'storage state' : 'signed out';
console.log(`wrote ${opts.out} from ${BASE}${opts.path} as ${who} at ${opts.width}px`);
await browser.close();
