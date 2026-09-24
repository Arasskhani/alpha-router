/**
 * Phone layout audit: a regression check for the app's phone layout, run by a
 * developer against a running local stack (it is not part of CI).
 *
 * It signs in as an admin and visits every route below at 360, 390 and 768 px
 * wide (touch, mobile viewport). On each page it checks:
 *
 *   1. Horizontal overflow: the page scrolls sideways. Always a failure.
 *   2. Unwrapped tables: a <table> wider than its parent (or reaching past the
 *      viewport's right edge) with no ancestor below the main column that
 *      scrolls horizontally (overflow-x: auto | scroll). Tables drawn as cards
 *      (table.data-table--cards, display: block on a phone) never count.
 *      Always a failure.
 *   3. Small touch targets: controls whose real hit area is under 44x44 CSS px.
 *      The hit area is measured with elementFromPoint from the control's centre
 *      outwards, so a wrapping label, a ::before hit area or a covering sibling
 *      count as a finger feels them. Inline text links are exempt.
 *   4. Small text fields: inputs, selects and textareas with a computed
 *      font-size under 16px, which iOS zooms into on focus.
 *
 * A route that redirects elsewhere (to /login, say), shows the route error
 * boundary or throws an uncaught page error fails too.
 *
 * Run it from frontend/ with the stack up:
 *
 *   PHONE_AUDIT_USER=admin PHONE_AUDIT_PASSWORD=... npm run audit:phone
 *
 *   PHONE_AUDIT_URL       app URL (default http://127.0.0.1:5173)
 *   PHONE_AUDIT_USER      admin username (required; the admin sees every route)
 *   PHONE_AUDIT_PASSWORD  its password (required)
 *   PHONE_AUDIT_CHROMIUM  optional path to a Chromium executable; otherwise
 *                         Playwright's own (npx playwright install chromium)
 *
 *   --routes=/app/chat,/admin/users  audit a subset of routes
 *   --widths=360,390                 audit a subset of widths
 *   --verbose                        list every small target, field and table
 *   --update                         write the current counts as the baseline
 *
 * Baseline policy: counts 3 and 4 are compared, per route and width, with
 * scripts/phone-audit.baseline.json. A count above its baseline fails; a count
 * below it is reported as an improvement to lock in with --update. Counts may
 * only go down: raise one only on purpose, with --update, and say why in the
 * commit. Overflow and unwrapped tables are never baselined. With --routes or
 * --widths, --update rewrites only the entries it measured.
 *
 * Exit codes: 0 pass, 1 a check failed, 2 bad configuration or setup.
 */
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { URL, fileURLToPath } from "node:url";
import { chromium } from "playwright";

// The measure* functions run in the page (page.evaluate), the rest in Node.
/* global console, document, window, getComputedStyle */

const BASELINE_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), "phone-audit.baseline.json");

const ALL_WIDTHS = [360, 390, 768];
const HEIGHT = 800;
const MIN_TARGET = 44;
const MIN_FIELD_FONT = 16;

const ALL_ROUTES = [
  "/app/manual", "/admin/docs", "/app/chat", "/app/projects", "/app/media", "/app/my-activity",
  "/admin", "/admin/operations", "/admin/database", "/admin/connections", "/admin/models",
  "/admin/api-keys", "/admin/chat-tools", "/admin/code-interpreter", "/admin/memory",
  "/admin/agents", "/admin/agents/studio", "/admin/knowledge", "/admin/agent-tools",
  "/admin/agent-evaluations", "/admin/agent-approvals", "/admin/agent-activity", "/admin/roles",
  "/admin/users", "/admin/deleted-users", "/admin/groups", "/admin/plans",
  "/admin/authentication", "/admin/security-settings", "/admin/smtp",
  "/admin/storage-management", "/admin/retention-policy", "/admin/reports",
  "/admin/project-usage", "/admin/logs", "/admin/admin-logs", "/admin/sign-in-activity",
];

// ---------------------------------------------------------------- config

function parseArgs(argv) {
  const opts = { update: false, verbose: false, routes: null, widths: null };
  for (const arg of argv) {
    const [name, value] = arg.split(/=(.*)/s);
    if (name === "--update") opts.update = true;
    else if (name === "--verbose") opts.verbose = true;
    else if (name === "--routes" && value) opts.routes = value.split(",").map((r) => r.trim()).filter(Boolean);
    else if (name === "--widths" && value) opts.widths = value.split(",").map(Number);
    else fail(`unknown argument: ${arg}`);
  }
  for (const route of opts.routes ?? []) {
    if (!ALL_ROUTES.includes(route)) fail(`unknown route: ${route} (known: ${ALL_ROUTES.join(", ")})`);
  }
  for (const width of opts.widths ?? []) {
    if (!ALL_WIDTHS.includes(width)) fail(`unsupported width: ${width} (supported: ${ALL_WIDTHS.join(", ")})`);
  }
  return opts;
}

/** A setup problem, not an audit failure: say what is wrong and exit 2. */
function fail(message) {
  console.error(`phone-audit: ${message}`);
  process.exit(2);
}

// ---------------------------------------------------------------- in-page checks
// These run in the browser through page.evaluate: no closures over Node values.

/** Horizontal page overflow and tables that are wider than their box with nothing to scroll them. */
function measureLayout() {
  const overflow = Math.max(0, document.scrollingElement.scrollWidth - window.innerWidth);
  const describe = (el) => el.tagName.toLowerCase() + [...el.classList].slice(0, 2).map((c) => "." + c).join("");
  const wideTables = [];
  for (const table of document.querySelectorAll("table")) {
    const rect = table.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    if (table.closest("[aria-hidden=true], [inert], [hidden]")) continue;
    // A card table is a stack of blocks on a phone: it wraps, it is never wide.
    if (table.classList.contains("data-table--cards") && getComputedStyle(table).display === "block") continue;
    const parent = table.parentElement;
    const pcs = getComputedStyle(parent);
    const parentWidth = parent.clientWidth - parseFloat(pcs.paddingLeft) - parseFloat(pcs.paddingRight);
    const wide = rect.width > parentWidth + 1 || rect.right > window.innerWidth + 1;
    if (!wide) continue;
    let scroller = null;
    for (let el = parent; el && !el.matches("main, .main-column, body"); el = el.parentElement) {
      if (["auto", "scroll"].includes(getComputedStyle(el).overflowX)) {
        scroller = el;
        break;
      }
    }
    if (!scroller) {
      wideTables.push({
        table: describe(table),
        parent: describe(parent),
        width: Math.round(rect.width),
        parentWidth: Math.round(parentWidth),
        right: Math.round(rect.right),
      });
    }
  }
  return { overflow, wideTables };
}

/** Text fields (the kinds iOS zooms into) with a computed font-size under the given minimum. */
function measureFields(minFont) {
  const NOT_TEXT = ["checkbox", "radio", "range", "color", "file", "hidden", "button", "submit", "reset", "image"];
  const small = [];
  for (const el of document.querySelectorAll("input, select, textarea")) {
    if (el.tagName === "INPUT" && NOT_TEXT.includes(el.type)) continue;
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.pointerEvents === "none" || el.disabled) continue;
    if (el.closest("[aria-hidden=true], [inert], [hidden]")) continue;
    const size = parseFloat(cs.fontSize);
    if (size < minFont) {
      const type = el.tagName === "INPUT" ? `[${el.type}]` : "";
      const label = (el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.name || "").trim().slice(0, 28);
      small.push({ kind: el.tagName.toLowerCase() + type, text: label, size });
    }
  }
  return small;
}

/**
 * The hit area of every control, measured: from the control's centre the page
 * is probed with elementFromPoint in the four directions, 1px at a time, until
 * a point no longer lands on the control (or on something that passes the tap
 * on to it). Controls whose centre is off-screen or covered are "occluded".
 */
function measureTargets() {
  const SEL = "button, a[href], [role=button], [role=tab], [role=switch], [role=checkbox], [role=radio],"
    + " [role=menuitem], [role=option], summary, select, textarea, input:not([type=hidden])";
  // A tap on one of these inside the composer box is its own, not the field's.
  const OWN = 'button, a[href], input, select, textarea, label, summary, [contenteditable],'
    + ' [role]:not([role="presentation"], [role="none"]), .alpha-router-prompt-queue, .alpha-router-pending-attachments';
  const items = [];
  const occluded = [];
  const kindOf = (el) => {
    const cls = [...el.classList].filter((c) => !/^(is-|active|selected|open)/.test(c)).slice(0, 2).join(".");
    const type = el.tagName === "INPUT" ? `[${el.type}]` : "";
    const role = el.getAttribute("role") ? `[role=${el.getAttribute("role")}]` : "";
    return el.tagName.toLowerCase() + type + role + (cls ? "." + cls : "");
  };
  const labelOf = (el) => (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.name || "")
    .trim().replace(/\s+/g, " ").slice(0, 28);
  const isInlineTextLink = (el) => {
    if (el.tagName !== "A" || getComputedStyle(el).display !== "inline") return false;
    // A link in the manual's text: a reference inside a document, sized by its lines.
    if (el.closest(".docs-main")) return true;
    // A link in a run of text: the sentence around it sets its size (WCAG 2.5.8 exempts it).
    const p = el.parentElement;
    return !!p && [...p.childNodes].some((n) => n !== el && n.nodeType === 3 && n.textContent.trim());
  };
  for (const el of document.querySelectorAll(SEL)) {
    const r0 = el.getBoundingClientRect();
    if (!r0.width || !r0.height) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.pointerEvents === "none" || el.disabled) continue;
    if (el.closest("[aria-hidden=true], [inert], [hidden]")) continue;
    if (isInlineTextLink(el)) continue;
    el.scrollIntoView({ block: "center", inline: "center" });
    const r = el.getBoundingClientRect();
    const cx = Math.round(r.left + r.width / 2);
    const cy = Math.round(r.top + r.height / 2);
    const inView = (x, y) => x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight;
    if (!inView(cx, cy)) {
      occluded.push({ kind: kindOf(el), text: labelOf(el), why: "off-screen" });
      continue;
    }
    const labels = el.labels ? [...el.labels] : [];
    // A card's select corner passes a tap on to its box (useTableCards).
    const corner = el.type === "checkbox" ? el.closest('.data-table--cards [data-card-role="select"]') : null;
    // The composer box passes a tap on anything but a control to its field (composerFocus).
    const composer = el.matches("textarea.alpha-router-composer-input") ? el.closest(".alpha-router-composer-box") : null;
    const owns = (t) => !!t && (t === el || el.contains(t)
      || labels.some((l) => l === t || l.contains(t))
      || (!!corner && corner.contains(t))
      || (!!composer && composer.contains(t) && !t.closest(OWN)));
    if (!owns(document.elementFromPoint(cx, cy))) {
      occluded.push({ kind: kindOf(el), text: labelOf(el), why: "covered" });
      continue;
    }
    const reach = (dx, dy) => {
      let d = 0;
      while (d < 60) {
        const x = cx + dx * (d + 1);
        const y = cy + dy * (d + 1);
        if (!inView(x, y) || !owns(document.elementFromPoint(x, y))) break;
        d++;
      }
      return d;
    };
    const w = reach(-1, 0) + reach(1, 0) + 1;
    const h = reach(0, -1) + reach(0, 1) + 1;
    items.push({ kind: kindOf(el), text: labelOf(el), w, h });
  }
  window.scrollTo(0, 0);
  return { items, occluded };
}

// ---------------------------------------------------------------- browser steps

async function launchBrowser() {
  const executablePath = process.env.PHONE_AUDIT_CHROMIUM || undefined;
  try {
    return await chromium.launch({ executablePath });
  } catch (err) {
    console.error(String(err.message || err).split("\n")[0]);
    fail(executablePath ? `could not launch Chromium at ${executablePath}` : "could not launch Chromium; run: npx playwright install chromium");
  }
}

async function logIn(page, base, user, password) {
  await page.goto(`${base}/login`);
  await page.getByLabel("Username", { exact: true }).fill(user);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.waitForURL((url) => !url.href.includes("/login"), { timeout: 15_000 });
}

async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 4_000 }).catch(() => {});
  await page.waitForTimeout(500);
}

/**
 * Start a new, empty chat so the counts do not depend on history. On a phone
 * the history (and its New chat button) is a drawer behind the topbar's menu
 * button; starting a chat closes it. Never sends a message.
 */
async function startFreshChat(page) {
  const newChat = page.locator("button.alpha-router-new-chat");
  if ((await newChat.count()) > 0 && (await newChat.isEnabled())) {
    const drawer = page.locator(".alpha-router-sidebar--drawer");
    const openDrawer = page.locator(".alpha-router-sidebar--drawer.is-open");
    if ((await drawer.count()) > 0 && (await openDrawer.count()) === 0) {
      await page.locator(".topbar-menu-btn").click();
      await openDrawer.waitFor({ timeout: 5_000 });
    }
    await newChat.click();
    if ((await drawer.count()) > 0) {
      await openDrawer.waitFor({ state: "detached", timeout: 5_000 });
    }
    await page.waitForTimeout(500); // the drawer's slide-out
  }
  await page
    .waitForFunction(() => !document.querySelector(".alpha-router-msg"), null, { timeout: 5_000 })
    .catch(() => {
      throw new Error("the chat still shows messages after starting a new chat");
    });
}

/** Visit one route and measure it. Returns { error } or the measurements. */
async function auditRoute(page, base, route, pageErrors) {
  pageErrors.length = 0;
  try {
    await page.goto(base + route);
    await settle(page);
    const landed = new URL(page.url()).pathname;
    if (landed !== route) return { error: `redirected to ${landed}` };
    if (route === "/app/chat") await startFreshChat(page);
    if ((await page.locator(".route-error").count()) > 0) return { error: "the route error boundary is showing" };
    const layout = await page.evaluate(measureLayout);
    const smallFields = await page.evaluate(measureFields, MIN_FIELD_FONT);
    const targets = await page.evaluate(measureTargets);
    if (pageErrors.length) return { error: `page error: ${pageErrors[0]}` };
    return {
      overflow: layout.overflow,
      wideTables: layout.wideTables,
      smallTargets: targets.items.filter((t) => t.w < MIN_TARGET || t.h < MIN_TARGET),
      smallFields,
      occluded: targets.occluded,
    };
  } catch (err) {
    return { error: String(err.message || err).split("\n")[0] };
  }
}

// ---------------------------------------------------------------- baseline

function readBaseline() {
  if (!fs.existsSync(BASELINE_PATH)) return {};
  try {
    return JSON.parse(fs.readFileSync(BASELINE_PATH, "utf8"));
  } catch (err) {
    fail(`cannot read ${BASELINE_PATH}: ${err.message}`);
  }
}

function sortKeys(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  return Object.fromEntries(Object.keys(value).sort().map((k) => [k, sortKeys(value[k])]));
}

function writeBaseline(baseline) {
  fs.writeFileSync(BASELINE_PATH, JSON.stringify(sortKeys(baseline), null, 2) + "\n");
}

/** Compare one route's counts with its baseline entry: { failures, notes }. */
function judge(result, expected, update) {
  const failures = [];
  const notes = [];
  if (result.error) return { failures: [result.error], notes };
  if (result.overflow > 0) failures.push(`page overflows by ${result.overflow}px`);
  for (const t of result.wideTables) {
    failures.push(`unwrapped table ${t.table} ${t.width}px wide in ${t.parent} (${t.parentWidth}px, right edge ${t.right}px)`);
  }
  if (update) return { failures, notes };
  if (!expected) {
    failures.push("no baseline entry (run with --update to record one)");
    return { failures, notes };
  }
  const counts = { smallTargets: result.smallTargets.length, smallFields: result.smallFields.length };
  const names = { smallTargets: "small targets", smallFields: "fields under 16px" };
  for (const key of Object.keys(counts)) {
    const was = expected[key] ?? 0;
    if (counts[key] > was) failures.push(`${names[key]} ${counts[key]} > baseline ${was}`);
    else if (counts[key] < was) notes.push(`${names[key]} improved ${was} -> ${counts[key]}, run with --update to lower the baseline`);
  }
  return { failures, notes };
}

// ---------------------------------------------------------------- output

function printTable(width, rows) {
  const header = ["route", "overflow", "wide tables", "small", "<16px", "baseline", "status"];
  const lines = rows.map(({ route, result, expected, verdict }) => [
    route,
    result.error ? "-" : result.overflow ? `${result.overflow}px` : "0",
    result.error ? "-" : String(result.wideTables.length),
    result.error ? "-" : String(result.smallTargets.length),
    result.error ? "-" : String(result.smallFields.length),
    expected ? `${expected.smallTargets}/${expected.smallFields}` : "none",
    verdict.failures.length ? "FAIL" : verdict.notes.length ? "improved" : "ok",
  ]);
  const widths = header.map((h, i) => Math.max(h.length, ...lines.map((l) => l[i].length)));
  const fmt = (cells) => cells.map((c, i) => c.padEnd(widths[i])).join("  ").trimEnd();
  console.log(`\n== ${width}px (baseline = small/<16px)`);
  console.log(fmt(header));
  console.log(widths.map((w) => "-".repeat(w)).join("  "));
  for (const line of lines) console.log(fmt(line));
}

function printDetails(rows, verbose) {
  for (const { route, result, verdict } of rows) {
    const lines = [...verdict.failures.map((f) => `FAIL ${f}`), ...verdict.notes.map((n) => `note ${n}`)];
    if (verbose && !result.error) {
      for (const t of result.smallTargets) lines.push(`small ${t.kind} "${t.text}" ${t.w}x${t.h}`);
      for (const f of result.smallFields) lines.push(`field ${f.kind} "${f.text}" ${f.size}px`);
      for (const o of result.occluded) lines.push(`occluded (${o.why}) ${o.kind} "${o.text}"`);
    }
    if (lines.length) console.log(`  ${route}\n${lines.map((l) => `    ${l}`).join("\n")}`);
  }
}

// ---------------------------------------------------------------- main

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const base = (process.env.PHONE_AUDIT_URL || "http://127.0.0.1:5173").replace(/\/+$/, "");
  const user = process.env.PHONE_AUDIT_USER;
  const password = process.env.PHONE_AUDIT_PASSWORD;
  if (!user || !password) fail("set PHONE_AUDIT_USER and PHONE_AUDIT_PASSWORD to an admin account on the stack under test");

  const routes = opts.routes ?? ALL_ROUTES;
  const widths = opts.widths ?? ALL_WIDTHS;
  const baseline = readBaseline();
  let failed = 0;
  let improved = 0;
  let audited = 0;

  const browser = await launchBrowser();
  try {
    for (const width of widths) {
      const context = await browser.newContext({ viewport: { width, height: HEIGHT }, isMobile: true, hasTouch: true });
      const page = await context.newPage();
      const pageErrors = [];
      page.on("pageerror", (err) => pageErrors.push(String(err.message || err).split("\n")[0]));
      try {
        await logIn(page, base, user, password);
      } catch (err) {
        fail(`could not sign in at ${base}/login as ${user}: ${String(err.message || err).split("\n")[0]}`);
      }

      const rows = [];
      for (const route of routes) {
        const result = await auditRoute(page, base, route, pageErrors);
        const expected = baseline[width]?.[route];
        const verdict = judge(result, expected, opts.update);
        rows.push({ route, result, expected, verdict });
        audited++;
        if (verdict.failures.length) failed++;
        else if (verdict.notes.length) improved++;
        if (opts.update && !result.error) {
          baseline[width] ??= {};
          baseline[width][route] = { smallFields: result.smallFields.length, smallTargets: result.smallTargets.length };
        }
      }
      printTable(width, rows);
      printDetails(rows, opts.verbose);
      await context.close();
    }
  } finally {
    await browser.close();
  }

  if (opts.update) {
    // A full run also drops entries for routes and widths no longer audited.
    if (!opts.routes && !opts.widths) {
      for (const width of Object.keys(baseline)) {
        if (!ALL_WIDTHS.includes(Number(width))) delete baseline[width];
        else for (const route of Object.keys(baseline[width])) if (!ALL_ROUTES.includes(route)) delete baseline[width][route];
      }
    }
    writeBaseline(baseline);
    console.log(`\nbaseline written to ${path.relative(process.cwd(), BASELINE_PATH)}`);
  }
  console.log(`\n${audited} route/width checks: ${audited - failed} passed` + (improved ? ` (${improved} improved)` : "") + `, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

await main();
