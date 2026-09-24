/**
 * Installable-app (PWA) end-to-end check: a developer check against a running
 * production build (npm run build, served by the backend), not part of CI.
 *
 * It drives Chromium through what makes Alpharouter an installable app and
 * fails if any step does not hold:
 *
 *   - Chrome's own install check (Page.getInstallabilityErrors) and manifest
 *     parser report no errors;
 *   - "/" sends a signed-out visitor to sign in and a signed-in user home;
 *   - the service worker registers after sign-in and controls the app;
 *   - API calls, the chat stream and /assets never come from the worker, and a
 *     streamed reply completes while it is active;
 *   - our offline page shows when the server cannot be reached and when a
 *     proxy answers 502, 503 or 504, the server's own errors pass through, and
 *     "Try again" returns to the app;
 *   - the retirement script (what /sw.js serves with
 *     PWA_SERVICE_WORKER_ENABLED=false; pytest covers that switch) replaces the
 *     worker, deletes its caches and unregisters;
 *   - the install suggestion, driven by a synthetic beforeinstallprompt:
 *     hidden before the app has been used, shown after, Not now kept, the
 *     profile menu's Install app opening the dialog once, appinstalled hiding
 *     everything, and an iPhone getting the Add to Home Screen steps;
 *   - the new-version notice after the server's build changes;
 *   - the "Alpharouter was updated" message when a page's code is gone.
 *
 * The browser runs a persistent profile (Chrome refuses installability in
 * incognito) with navigator.webdriver off, so the worker registers as it would
 * for a person; nothing test-only ships in the app. Requests the worker makes
 * are routed through Playwright (PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS)
 * to stand in for a server that is down or a proxy error.
 *
 * Run it from frontend/ against the production build (localhost counts as a
 * secure context; use the HTTPS address otherwise):
 *
 *   PWA_E2E_USER=admin PWA_E2E_PASSWORD=... npm run e2e:pwa
 *
 *   PWA_E2E_URL        app URL (default http://127.0.0.1:8080)
 *   PWA_E2E_USER       an account without two-factor sign-in (required)
 *   PWA_E2E_PASSWORD   its password (required)
 *   PWA_E2E_CHROMIUM   optional path to a Chromium executable; otherwise
 *                      Playwright's own (npx playwright install chromium)
 *
 * It sends one short chat message to the account's default model.
 * Exit codes: 0 every step passed, 1 a step failed, 2 bad configuration or setup.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { URL } from "node:url";

// Must be set before Playwright starts: lets context.route() see the worker's own requests.
process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = "1";
const { chromium } = await import("playwright");

/* global console, document, window, navigator, caches, localStorage, fetch, Event, history, PopStateEvent */

const BASE = (process.env.PWA_E2E_URL || "http://127.0.0.1:8080").replace(/\/+$/, "");
const USER = process.env.PWA_E2E_USER;
const PASSWORD = process.env.PWA_E2E_PASSWORD;
const EXECUTABLE = process.env.PWA_E2E_CHROMIUM || undefined;
const PREFS_KEY = "alpha_router_install_prompt";
const OFFLINE_HEADING = "Can't reach Alpharouter right now";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";

function setupError(message) {
  console.error(`pwa-e2e: ${message}`);
  process.exit(2);
}

if (!USER || !PASSWORD) setupError("set PWA_E2E_USER and PWA_E2E_PASSWORD to an account on the stack under test");

const results = [];

/** The page a failed step is photographed from. */
let currentPage = null;

/** Run one step; a failure is recorded (with a screenshot) and the run goes on. */
async function step(name, fn) {
  try {
    const note = await fn();
    results.push({ name, ok: true, note: note || "" });
    console.log(`  ok    ${name}${note ? ` (${note})` : ""}`);
  } catch (err) {
    results.push({ name, ok: false, note: String(err?.message || err).split("\n")[0] });
    console.log(`  FAIL  ${name}\n        ${String(err?.message || err).split("\n")[0]}`);
    if (currentPage) {
      const shot = path.join(os.tmpdir(), `pwa-e2e-${results.length}.png`);
      await currentPage.screenshot({ path: shot }).then(
        () => console.log(`        screenshot: ${shot}`),
        () => undefined,
      );
    }
  }
}

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

async function logIn(page) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Username", { exact: true }).fill(USER);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 20_000 });
}

/** A synthetic Chromium install event; window.__promptCalls counts prompt(). */
function fireInstallEvent(page, outcome = "dismissed") {
  return page.evaluate((answer) => {
    const event = new Event("beforeinstallprompt", { cancelable: true });
    window.__promptCalls = window.__promptCalls || 0;
    event.prompt = () => {
      window.__promptCalls += 1;
      return Promise.resolve();
    };
    event.userChoice = Promise.resolve({ outcome: answer, platform: "web" });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  }, outcome);
}

/** Go to another /app section and back through the tab bar or history, without reloading. */
async function routeChange(page, to) {
  await page.evaluate((target) => {
    history.pushState({}, "", target);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, to);
  await page.waitForTimeout(700);
}

async function launch(options = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pwa-e2e-"));
  try {
    return await chromium.launchPersistentContext(dir, {
      executablePath: EXECUTABLE,
      headless: true,
      args: ["--disable-blink-features=AutomationControlled"],
      ...options,
    });
  } catch (err) {
    setupError(
      `could not launch Chromium${EXECUTABLE ? ` at ${EXECUTABLE}` : "; run: npx playwright install chromium"} (${String(err.message).split("\n")[0]})`,
    );
  }
}

// ---------------------------------------------------------------- the installed app

async function installedApp() {
  console.log("\nThe installable app (desktop Chromium)");
  const context = await launch({ viewport: { width: 1280, height: 800 } });
  const page = context.pages()[0] ?? (await context.newPage());
  currentPage = page;
  try {
    await step("Chrome's install check and manifest parser report no errors", async () => {
      await page.goto(`${BASE}/login`);
      await page.waitForTimeout(1500);
      const cdp = await context.newCDPSession(page);
      const { installabilityErrors } = await cdp.send("Page.getInstallabilityErrors");
      expect(installabilityErrors.length === 0, `installability errors: ${JSON.stringify(installabilityErrors)}`);
      const manifest = await cdp.send("Page.getAppManifest");
      expect(manifest.url.endsWith("/manifest.webmanifest"), `manifest at ${manifest.url}`);
      expect(manifest.errors.length === 0, `manifest errors: ${JSON.stringify(manifest.errors)}`);
    });

    await step('"/" sends a signed-out visitor to the sign-in page', async () => {
      await page.goto(`${BASE}/`);
      await page.waitForURL((url) => url.pathname === "/login", { timeout: 10_000 });
      // The refused session check also sends the page to /login; let that settle.
      await page.waitForLoadState("networkidle").catch(() => undefined);
      await page.waitForTimeout(500);
    });

    try {
      await logIn(page);
    } catch (err) {
      setupError(`could not sign in at ${BASE}/login as ${USER} (no two-factor accounts): ${String(err.message).split("\n")[0]}`);
    }

    await step('"/" sends a signed-in user to their home page', async () => {
      await page.goto(`${BASE}/`);
      await page.waitForURL((url) => url.pathname.startsWith("/app/") || url.pathname.startsWith("/admin"), {
        timeout: 10_000,
      });
      return new URL(page.url()).pathname;
    });

    await step("the service worker registers after sign-in and controls the app", async () => {
      await page.waitForFunction(
        () => navigator.serviceWorker.getRegistrations().then((list) => list.some((r) => r.active)),
        null,
        { timeout: 20_000 },
      );
      await page.goto(`${BASE}/app/chat`);
      await page.waitForTimeout(1200);
      expect(await page.evaluate(() => Boolean(navigator.serviceWorker.controller)), "no controller after a reload");
      const cacheNames = await page.evaluate(() => caches.keys());
      expect(cacheNames.length === 1 && /^alpharouter-offline-[0-9a-f]{12}$/.test(cacheNames[0]), `caches: ${cacheNames}`);
    });

    await step("API calls, the chat stream and /assets never come from the worker; a reply completes", async () => {
      const seen = [];
      const onResponse = (response) => {
        const url = new URL(response.url());
        if (url.origin === new URL(BASE).origin && /^\/(api|assets)\//.test(url.pathname)) {
          seen.push({ path: url.pathname, fromWorker: response.fromServiceWorker() });
        }
      };
      page.on("response", onResponse);
      await page.reload();
      await page.waitForTimeout(1500);
      const composer = page.locator("textarea.alpha-router-composer-input");
      const before = await page.locator(".alpha-router-msg").count();
      await composer.fill("Say hello in five words (installable-app check).");
      await composer.press("Enter");
      const last = page.locator(".alpha-router-msg").last();
      await page.waitForFunction(
        (count) => {
          const messages = document.querySelectorAll(".alpha-router-msg");
          const reply = messages[messages.length - 1];
          return (
            messages.length >= count + 2 && !document.querySelector(".alpha-router-stop") && reply?.textContent?.trim()
          );
        },
        before,
        { timeout: 60_000 },
      );
      await page.waitForTimeout(800);
      page.off("response", onResponse);
      const reply = (await last.innerText()).trim();
      expect(reply && !/\bError:/.test(reply), `the reply did not complete: ${reply.slice(0, 120)}`);
      const fromWorker = seen.filter((r) => r.fromWorker).map((r) => r.path);
      expect(seen.some((r) => r.path.startsWith("/api/chat")), "no chat request was seen");
      expect(fromWorker.length === 0, `answered by the worker: ${fromWorker.join(", ")}`);
      return `${seen.length} requests, none from the worker`;
    });

    await step("our page shows when the server cannot be reached", async () => {
      await context.route("**/admin/users", (route) => route.abort("connectionrefused"));
      await page.goto(`${BASE}/admin/users`);
      await page.getByRole("heading", { name: OFFLINE_HEADING }).waitFor({ timeout: 10_000 });
      await context.unroute("**/admin/users");
    });

    for (const status of [502, 503, 504]) {
      await step(`our page shows when a proxy answers ${status}`, async () => {
        await context.route("**/admin/roles", (route) =>
          route.fulfill({ status, contentType: "text/html", body: `<h1>proxy ${status}</h1>` }),
        );
        await page.goto(`${BASE}/admin/roles`);
        await page.getByRole("heading", { name: OFFLINE_HEADING }).waitFor({ timeout: 10_000 });
        await context.unroute("**/admin/roles");
      });
    }

    await step("the server's own errors pass through the worker", async () => {
      await context.route("**/admin/groups", (route) =>
        route.fulfill({ status: 500, contentType: "text/html", body: "<h1>server says 500</h1>" }),
      );
      await page.goto(`${BASE}/admin/groups`);
      await page.getByRole("heading", { name: "server says 500" }).waitFor({ timeout: 10_000 });
      await context.unroute("**/admin/groups");
    });

    await step('"Try again" on our page returns to the app', async () => {
      await context.route("**/admin/users", (route) => route.abort("connectionrefused"));
      await page.goto(`${BASE}/admin/users`);
      await page.getByRole("heading", { name: OFFLINE_HEADING }).waitFor({ timeout: 10_000 });
      await context.unroute("**/admin/users");
      await page.getByRole("link", { name: "Try again" }).click();
      await page.locator(".app-topbar").waitFor({ timeout: 15_000 });
    });

    await step("a missing page chunk after an upgrade says the app was updated", async () => {
      await page.goto(`${BASE}/admin`);
      await page.waitForTimeout(1200);
      await page.route(/\/assets\/Users-[\w-]+\.js$/, (route) => route.fulfill({ status: 404, body: "Not Found" }));
      await routeChange(page, "/admin/users");
      await page.getByRole("heading", { name: "Alpharouter was updated" }).waitFor({ timeout: 10_000 });
      await page.unroute(/\/assets\/Users-[\w-]+\.js$/);
    });

    await step("the retirement script unregisters the worker and deletes its caches", async () => {
      // What /sw.js serves while PWA_SERVICE_WORKER_ENABLED=false (the server side is tested in pytest).
      // Registered in its place here, it replaces the running worker as an update would.
      await page.goto(`${BASE}/app/chat`);
      const outcome = await page.evaluate(() =>
        navigator.serviceWorker.register("/sw-retire.js", { scope: "/", updateViaCache: "none" }).then(
          () => "registered",
          (err) => String(err),
        ),
      );
      expect(outcome === "registered", `could not register sw-retire.js: ${outcome}`);
      await page.waitForFunction(
        () =>
          Promise.all([navigator.serviceWorker.getRegistrations(), caches.keys()]).then(
            ([registrations, names]) => registrations.length === 0 && !names.some((n) => n.startsWith("alpharouter-")),
          ),
        null,
        { timeout: 20_000 },
      );
    });
  } finally {
    await context.close();
  }
}

// ---------------------------------------------------------------- the install suggestion

async function installSuggestion() {
  console.log("\nThe install suggestion (Android phone)");
  const context = await launch({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = context.pages()[0] ?? (await context.newPage());
  currentPage = page;
  try {
    await logIn(page);
    await page.goto(`${BASE}/app/chat`);
    await page.waitForTimeout(1200);
    const banner = page.locator(".install-banner");

    await step("the browser's own prompt is held back", async () => {
      expect(await fireInstallEvent(page), "beforeinstallprompt was not prevented");
    });

    await step("nothing is suggested before the app has been used here", async () => {
      await page.evaluate((key) => {
        const today = new Date();
        const day = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
        localStorage.setItem(key, JSON.stringify({ days: 1, lastDay: day }));
      }, PREFS_KEY);
      await routeChange(page, "/app/projects");
      await routeChange(page, "/app/chat");
      expect((await banner.count()) === 0, "the bar showed on the first day");
    });

    await step("the suggestion appears on a route change once the app has been used", async () => {
      await page.evaluate((key) => localStorage.setItem(key, JSON.stringify({ days: 2, lastDay: "2000-01-01" })), PREFS_KEY);
      await routeChange(page, "/app/projects");
      await banner.waitFor({ timeout: 5_000 });
      expect((await banner.getAttribute("role")) === "region", "the bar is not a region");
      for (const name of ["Install", "Not now"]) {
        const box = await banner.getByRole("button", { name, exact: true }).boundingBox();
        expect(box && box.height >= 44 && box.width >= 44, `${name} is ${box?.width}x${box?.height}`);
      }
    });

    await step("Not now hides it and keeps the answer", async () => {
      await banner.getByRole("button", { name: "Not now", exact: true }).click();
      await banner.waitFor({ state: "detached", timeout: 5_000 });
      const prefs = await page.evaluate((key) => JSON.parse(localStorage.getItem(key)), PREFS_KEY);
      expect(prefs.dismissals === 1 && prefs.snoozedUntil > Date.now(), `saved: ${JSON.stringify(prefs)}`);
      await page.reload();
      await page.waitForTimeout(1200);
      await fireInstallEvent(page);
      await routeChange(page, "/app/chat");
      expect((await banner.count()) === 0, "the bar came back while snoozed");
    });

    await step("Install app in the profile menu opens the browser's dialog once", async () => {
      await page.evaluate(() => {
        window.__promptCalls = 0;
      });
      await page.locator(".user-profile-trigger").click();
      await page.getByRole("menuitem", { name: "Install app" }).click();
      await page.waitForTimeout(300);
      expect((await page.evaluate(() => window.__promptCalls)) === 1, "prompt() was not called exactly once");
    });

    await step("once installed, nothing offers installing any more", async () => {
      await fireInstallEvent(page);
      await page.evaluate(() => window.dispatchEvent(new Event("appinstalled")));
      await page.locator(".user-profile-trigger").click();
      await page.waitForTimeout(300);
      expect((await page.getByRole("menuitem", { name: "Install app" }).count()) === 0, "Install app is still offered");
      const prefs = await page.evaluate((key) => JSON.parse(localStorage.getItem(key)), PREFS_KEY);
      expect(prefs.done === true, "the install was not remembered");
    });

    await step("the new-version notice appears when the server's build changes", async () => {
      await page.route(`${BASE}/`, async (route) => {
        if (route.request().resourceType() === "document") return route.continue();
        const response = await route.fetch();
        const body = (await response.text()).replace(/\/assets\/index-[\w-]+\.js/, "/assets/index-NEWBUILD.js");
        return route.fulfill({ response, body });
      });
      await page.clock.install();
      await page.goto(`${BASE}/app/chat`);
      await page.waitForTimeout(1200);
      await page.clock.runFor(60 * 60 * 1000 + 1000);
      await page.locator(".app-notice").waitFor({ timeout: 10_000 });
      await page.unroute(`${BASE}/`);
    });
  } finally {
    await context.close();
  }

  console.log("\nThe install suggestion (iPhone)");
  const iphone = await launch({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, userAgent: IPHONE });
  // Chromium fires its own install event even with an iPhone user agent; iOS has none.
  await iphone.addInitScript(() =>
    window.addEventListener("beforeinstallprompt", (event) => event.stopImmediatePropagation(), true),
  );
  const ipage = iphone.pages()[0] ?? (await iphone.newPage());
  currentPage = ipage;
  try {
    await logIn(ipage);
    await ipage.goto(`${BASE}/app/chat`);
    await ipage.waitForTimeout(1200);
    await step("an iPhone is shown how to add the app to the Home Screen", async () => {
      await ipage.evaluate((key) => localStorage.setItem(key, JSON.stringify({ days: 2, lastDay: "2000-01-01" })), PREFS_KEY);
      await routeChange(ipage, "/app/projects");
      await ipage.locator(".install-banner").getByRole("button", { name: "How to install" }).click();
      const dialog = ipage.getByRole("dialog");
      await dialog.waitFor({ timeout: 5_000 });
      const text = await dialog.innerText();
      expect(text.includes("Add to Home Screen") && text.includes("Open this page in Safari"), "the steps are missing");
      const prefs = await ipage.evaluate((key) => JSON.parse(localStorage.getItem(key)), PREFS_KEY);
      expect(prefs.dismissals === 1, "showing the steps did not count as the answer");
    });
  } finally {
    await iphone.close();
  }
}

// ---------------------------------------------------------------- main

console.log(`pwa-e2e against ${BASE}`);
try {
  const health = await fetch(`${BASE}/health`);
  if (!health.ok) setupError(`${BASE}/health answered ${health.status}`);
  const sw = await fetch(`${BASE}/sw.js`);
  if (!sw.ok) setupError(`${BASE}/sw.js answered ${sw.status}: serve the production build (npm run build)`);
} catch (err) {
  setupError(`cannot reach ${BASE}: ${err.message}`);
}

await installedApp();
await installSuggestion();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length} steps: ${results.length - failed.length} passed, ${failed.length} failed`);
process.exit(failed.length ? 1 : 0);
