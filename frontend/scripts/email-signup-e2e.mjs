/**
 * Email sign-up end-to-end check: a developer check against a running build
 * (npm run build, served by the backend), not part of CI.
 *
 * The script runs its own mail sink and points the stack's SMTP settings at
 * it, turns email sign-up and password reset on for one test domain, and then,
 * in a browser with no session:
 *
 *   - the sign-in page offers "Create an account" and "Forgot password?";
 *   - an address outside the allowed domains is refused;
 *   - the code arrives by email, never in the subject; a wrong code is
 *     refused with the tries left; the right one leads on;
 *   - a reserved username is refused as it is typed, a free one is available;
 *   - the server refuses a password that contains the username;
 *   - the account is created and signed in, with the user role and the
 *     default plan;
 *   - signing up again with the same address offers a reset; the reset takes
 *     an emailed code, refuses the current password, ends on the sign-in form
 *     with the username filled in, and signs the earlier session out;
 *   - the new password signs in; Sign-in Activity has the sign-up and the
 *     reset; the admin tab shows the settings; on a phone the whole form
 *     can be scrolled to.
 *
 * Run it from frontend/ against a development stack:
 *
 *   SIGNUP_E2E_USER=admin SIGNUP_E2E_PASSWORD=... node scripts/email-signup-e2e.mjs
 *
 *   SIGNUP_E2E_URL        app URL (default http://127.0.0.1:8080)
 *   SIGNUP_E2E_USER       a super administrator without two-factor sign-in (required)
 *   SIGNUP_E2E_PASSWORD   its password (required)
 *   SIGNUP_E2E_SMTP_PORT  port for the mail sink on 127.0.0.1 (default 2526)
 *   SIGNUP_E2E_CHROMIUM   optional path to a Chromium executable
 *
 * Each run asks for four sign-up codes from this machine's address, and the
 * server allows ten in ten minutes per address: run it at most twice in ten
 * minutes, or the third run is refused codes ("Too many attempts").
 *
 * It refuses to run when the stack's SMTP settings point at a mail server
 * other than this machine: it would replace them, and a saved SMTP password
 * cannot be read back to restore. At the end it puts the email sign-up
 * settings back, puts back SMTP settings that had no password, and moves the
 * account it made to Deleted Users.
 * Exit codes: 0 every step passed, 1 a step failed, 2 bad configuration or setup.
 */
import net from "node:net";
import process from "node:process";

const { chromium } = await import("playwright");

/* global console, setTimeout, Buffer */

const BASE = (process.env.SIGNUP_E2E_URL || "http://127.0.0.1:8080").replace(/\/+$/, "");
const ADMIN = process.env.SIGNUP_E2E_USER;
const ADMIN_PASSWORD = process.env.SIGNUP_E2E_PASSWORD;
const SMTP_PORT = Number(process.env.SIGNUP_E2E_SMTP_PORT || 2526);
if (!ADMIN || !ADMIN_PASSWORD) {
  console.error("email-signup-e2e: set SIGNUP_E2E_USER and SIGNUP_E2E_PASSWORD to a super administrator without two-factor sign-in");
  process.exit(2);
}

const RUN = Date.now().toString(36);
const DOMAIN = "signup-check.test";
const EMAIL = `person.${RUN}@${DOMAIN}`;
const USERNAME = `person-${RUN}`;
const FIRST_PASSWORD = `Kp-${RUN.toUpperCase()}-strong9!`;
const NEW_PASSWORD = `Qw-${RUN.toUpperCase()}-fresh7#`;
const LOOPBACK = new Set(["127.0.0.1", "localhost", "::1"]);
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const results = [];

async function step(name, work) {
  try {
    const note = await work();
    results.push({ name, ok: true });
    console.log(`  ok    ${name}${note ? ` (${note})` : ""}`);
  } catch (err) {
    results.push({ name, ok: false });
    console.log(`  FAIL  ${name}\n        ${String(err?.message || err).split("\n")[0]}`);
  }
}

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

// ── The mail sink: just enough SMTP for a plain connection with no login ──

const mailbox = [];

function decodeBody(raw) {
  const split = raw.indexOf("\r\n\r\n");
  const headers = split >= 0 ? raw.slice(0, split) : raw;
  let body = split >= 0 ? raw.slice(split + 4) : "";
  const unfolded = headers.replace(/\r\n[ \t]+/g, " ");
  const header = (name) => new RegExp(`^${name}:\\s*(.*)$`, "im").exec(unfolded)?.[1]?.trim() ?? "";
  const encoding = header("Content-Transfer-Encoding").toLowerCase();
  if (encoding === "base64") body = Buffer.from(body.replace(/\s+/g, ""), "base64").toString("utf8");
  if (encoding === "quoted-printable") {
    body = body
      .replace(/=\r\n/g, "")
      .replace(/=([0-9A-F]{2})/gi, (_m, hex) => String.fromCharCode(parseInt(hex, 16)));
  }
  return { subject: header("Subject"), body };
}

const sink = net.createServer((socket) => {
  let buffer = "";
  let inData = false;
  let data = "";
  let to = [];
  const say = (line) => socket.write(`${line}\r\n`);
  say("220 signup-check sink");
  socket.on("data", (chunk) => {
    buffer += chunk.toString("utf8");
    for (;;) {
      if (inData) {
        const end = buffer.indexOf("\r\n.\r\n");
        if (end < 0) return;
        data += buffer.slice(0, end);
        buffer = buffer.slice(end + 5);
        inData = false;
        mailbox.push({ to, ...decodeBody(data.replace(/^\.\./gm, ".")) });
        data = "";
        to = [];
        say("250 queued");
        continue;
      }
      const eol = buffer.indexOf("\r\n");
      if (eol < 0) return;
      const line = buffer.slice(0, eol);
      buffer = buffer.slice(eol + 2);
      const verb = line.slice(0, 4).toUpperCase();
      if (verb === "EHLO") {
        say("250-signup-check");
        say("250 8BITMIME");
      } else if (verb === "RCPT") {
        to.push((/<([^>]*)>/.exec(line)?.[1] ?? "").toLowerCase());
        say("250 ok");
      } else if (verb === "DATA") {
        inData = true;
        say("354 end with <CRLF>.<CRLF>");
      } else if (verb === "QUIT") {
        say("221 bye");
        socket.end();
        return;
      } else {
        say("250 ok"); // HELO, MAIL, RSET, NOOP
      }
    }
  });
  socket.on("error", () => undefined);
});

async function codeFor(address, seen) {
  for (let i = 0; i < 100; i += 1) {
    const mail = mailbox.slice(seen).find((m) => m.to.includes(address));
    if (mail) {
      const code = /^ {4}(\d{6})\s*$/m.exec(mail.body)?.[1];
      expect(code, `no code in the email: ${mail.body.slice(0, 120)}`);
      return { code, mail };
    }
    await sleep(200);
  }
  throw new Error(`no email reached ${address}`);
}

// ── Setup ──

try {
  await new Promise((resolve, reject) => {
    sink.once("error", reject);
    sink.listen(SMTP_PORT, "127.0.0.1", resolve);
  });
} catch (err) {
  console.error(`email-signup-e2e: cannot listen on 127.0.0.1:${SMTP_PORT}: ${err?.message || err}`);
  process.exit(2);
}

const browser = await chromium.launch(process.env.SIGNUP_E2E_CHROMIUM ? { executablePath: process.env.SIGNUP_E2E_CHROMIUM } : {});

async function session(context) {
  const csrf = (await context.cookies()).find((c) => c.name.includes("csrf"))?.value;
  return { "X-CSRF-Token": csrf, "Content-Type": "application/json" };
}

async function freshPage(width = 1280) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await context.newPage();
  await page.goto(`${BASE}/login`);
  return { context, page };
}

async function signIn(username, password) {
  const { context, page } = await freshPage();
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 20_000 });
  return { context, page, headers: await session(context) };
}

let admin;
let api;
let savedSmtp = null;
let savedSignup = null;
let planId = null;
try {
  admin = await signIn(ADMIN, ADMIN_PASSWORD);
  api = (path, init = {}) => admin.page.request.fetch(`${BASE}${path}`, { headers: admin.headers, ...init });

  savedSmtp = await (await api("/api/admin/smtp")).json();
  if (savedSmtp && !LOOPBACK.has(String(savedSmtp.host).trim().toLowerCase())) {
    throw new Error(
      `SMTP points at ${savedSmtp.host}: this check would replace it. Run it against a development stack.`,
    );
  }
  const smtp = await api("/api/admin/smtp", {
    method: "PUT",
    data: {
      host: "127.0.0.1",
      port: SMTP_PORT,
      username: null,
      password: null,
      from_address: "Alpharouter <no-reply@signup-check.test>",
      security: "none",
      verify_certificate: true,
    },
  });
  expect(smtp.ok(), `saving SMTP answered ${smtp.status()}: ${(await smtp.text()).slice(0, 200)}`);

  let plans = await (await api("/api/admin/plans")).json();
  if (!Array.isArray(plans) || plans.length === 0) {
    await api("/api/admin/plans", { method: "POST", data: { name: "Email sign-up check", monthly_budget_usd: 5 } });
    plans = await (await api("/api/admin/plans")).json();
  }
  planId = plans[0]?.id ?? null;

  savedSignup = await (await api("/api/admin/authentication/email-signup")).json();
  const on = await api("/api/admin/authentication/email-signup", {
    method: "PUT",
    data: { enabled: true, allowed_domains: [DOMAIN], default_plan_id: planId, reset_enabled: true },
  });
  expect(on.ok(), `turning email sign-up on answered ${on.status()}: ${(await on.text()).slice(0, 200)}`);
} catch (err) {
  console.error(`email-signup-e2e: setup failed: ${String(err?.message || err).split("\n")[0]}`);
  await browser.close();
  sink.close();
  process.exit(2);
}

// ── Sign-up ──

const visitor = await freshPage();
const page = visitor.page;
let signedUp = null;

await step("the sign-in page offers to create an account and to reset a password", async () => {
  await page.getByRole("button", { name: "Create an account" }).waitFor({ timeout: 15_000 });
  expect(await page.getByRole("button", { name: "Forgot password?" }).isVisible(), "no Forgot password?");
  await page.getByRole("button", { name: "Create an account" }).click();
  await page.locator(".login-panel__title", { hasText: "Create an account" }).waitFor();
});

await step("an address outside the allowed domains is refused", async () => {
  await page.locator("#signup-email").fill(`someone.${RUN}@elsewhere.test`);
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByText(`Accounts can be created only with an email address at ${DOMAIN}.`).waitFor({ timeout: 10_000 });
  expect(!mailbox.some((m) => m.to.some((t) => t.endsWith("@elsewhere.test"))), "an email went to the refused address");
});

let code = "";
await step("the code arrives by email, not in the subject", async () => {
  const seen = mailbox.length;
  await page.locator("#signup-email").fill(EMAIL);
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByText(`We sent a 6-digit code to ${EMAIL}`).waitFor({ timeout: 15_000 });
  const got = await codeFor(EMAIL, seen);
  code = got.code;
  expect(got.mail.subject === "Your Alpharouter sign-up code", `subject: ${got.mail.subject}`);
  expect(!/\d{6}/.test(got.mail.subject), "the code is in the subject");
  return `subject "${got.mail.subject}"`;
});

await step("a wrong code is refused with the tries left", async () => {
  const wrong = String((Number(code) + 1) % 1_000_000).padStart(6, "0");
  await page.locator("#signup-code").fill(wrong);
  await page.getByRole("button", { name: "Verify" }).click();
  await page.getByText("That code is not right. 4 tries left.").waitFor({ timeout: 10_000 });
  const resend = page.getByRole("button", { name: /Send a new code/ });
  expect(await resend.isDisabled(), "a new code can be asked for at once");
});

await step("the right code leads to the username and password", async () => {
  await page.locator("#signup-code").fill(code);
  await page.getByRole("button", { name: "Verify" }).click();
  await page.locator("#signup-username").waitFor({ timeout: 10_000 });
  const suggested = await page.locator("#signup-username").inputValue();
  expect(suggested.startsWith("person."), `suggested username: ${suggested}`);
  return `suggested "${suggested}"`;
});

await step("a reserved username is refused as it is typed, a free one is available", async () => {
  await page.locator("#signup-username").fill("admin");
  await page.getByText("That username is reserved. Choose another.").waitFor({ timeout: 10_000 });
  expect(await page.getByRole("button", { name: "Create account" }).isDisabled(), "Create account is enabled");
  await page.locator("#signup-username").fill(USERNAME);
  await page.locator(".login-form__ok", { hasText: "Available" }).waitFor({ timeout: 10_000 });
});

await step("the password rules tick off, and the server refuses a password with the username", async () => {
  const weak = `${USERNAME}-Aa1!`;
  await page.locator("#signup-password").fill(weak);
  await page.locator("#signup-confirm").fill(weak);
  const unmet = await page
    .locator("#signup-password-rules li:not(.password-rules__rule--met)")
    .evaluateAll((items) => items.map((li) => li.textContent));
  expect(unmet.some((text) => /username/i.test(text ?? "")), `the personal rule is not shown unmet: ${unmet.join(" | ")}`);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.getByText("Password must not contain your username").waitFor({ timeout: 10_000 });
});

await step("the account is created and signed in, with the user role and the default plan", async () => {
  await page.locator("#signup-password").fill(FIRST_PASSWORD);
  await page.locator("#signup-confirm").fill(FIRST_PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 20_000 });
  const me = await (await page.request.get(`${BASE}/api/auth/session`)).json();
  expect(me.username === USERNAME, `signed in as ${me.username}`);
  const rows = await (await api(`/api/admin/users?username=${encodeURIComponent(USERNAME)}`)).json();
  const row = (Array.isArray(rows) ? rows : rows.items ?? []).find((u) => u.username === USERNAME);
  expect(row, "the account is not in the user list");
  signedUp = row;
  expect(row.is_active === true, "the account is not active");
  expect(row.auth_provider === "local", `auth provider ${row.auth_provider}`);
  expect(JSON.stringify(row.roles ?? row.role ?? "").includes("user"), `roles ${JSON.stringify(row.roles ?? row.role)}`);
  if (planId != null) {
    expect(row.user_plan_mode === "assigned" && row.user_plan_id === planId, `plan ${row.user_plan_mode} ${row.user_plan_id}`);
  }
  return new URL(page.url()).pathname;
});

// ── Password reset ──

const second = await freshPage();
await step("signing up again with the same address offers a reset", async () => {
  await second.page.getByRole("button", { name: "Create an account" }).click();
  await second.page.locator("#signup-email").fill(EMAIL);
  await second.page.getByRole("button", { name: "Send code" }).click();
  await second.page.getByText("An account already uses this email.").waitFor({ timeout: 10_000 });
  await second.page.getByRole("button", { name: "Reset password" }).click();
  await second.page.locator(".login-panel__title", { hasText: "Reset password" }).waitFor();
  expect((await second.page.locator("#reset-email").inputValue()) === EMAIL, "the address is not filled in");
});

await step("the reset takes an emailed code and refuses the current password", async () => {
  const seen = mailbox.length;
  await second.page.getByRole("button", { name: "Send code" }).click();
  const got = await codeFor(EMAIL, seen);
  expect(got.mail.subject === "Your Alpharouter password reset code", `subject: ${got.mail.subject}`);
  await second.page.locator("#reset-code").fill(got.code);
  await second.page.getByRole("button", { name: "Verify" }).click();
  await second.page.getByText(`Choose a new password for ${USERNAME}`).waitFor({ timeout: 10_000 });
  await second.page.locator("#reset-password").fill(FIRST_PASSWORD);
  await second.page.locator("#reset-confirm").fill(FIRST_PASSWORD);
  await second.page.getByRole("button", { name: "Set new password" }).click();
  await second.page.getByText("Choose a password different from your current one.").waitFor({ timeout: 10_000 });
});

await step("the new password is set and the sign-in form has the username", async () => {
  await second.page.locator("#reset-password").fill(NEW_PASSWORD);
  await second.page.locator("#reset-confirm").fill(NEW_PASSWORD);
  await second.page.getByRole("button", { name: "Set new password" }).click();
  await second.page.getByText("Your password has been changed. Sign in with your new password.").waitFor({ timeout: 10_000 });
  expect((await second.page.locator("#login-username").inputValue()) === USERNAME, "the username is not filled in");
});

await step("the reset signed the earlier session out", async () => {
  const answer = await page.request.get(`${BASE}/api/auth/session`);
  expect(answer.status() === 401, `the earlier session answered ${answer.status()}`);
});

await step("the new password signs in", async () => {
  await second.page.locator("#login-password").fill(NEW_PASSWORD);
  await second.page.getByRole("button", { name: "Continue" }).click();
  await second.page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 20_000 });
});

await step("Sign-in Activity has the sign-up, the refusals and the reset", async () => {
  const events = async (query) =>
    (await (await api(`/api/admin/sign-in-activity?${query}`)).json()).items ?? [];
  const mine = await events(`username=${encodeURIComponent(USERNAME)}&limit=100`);
  const types = mine.map((e) => e.event_type);
  for (const type of ["signup_completed", "password_reset", "session_revoked", "login_success"]) {
    expect(types.includes(type), `no ${type} for the account (has ${[...new Set(types)].join(", ")})`);
  }
  const failed = await events("event_type=signup_failed&limit=100");
  expect(failed.some((e) => e.reason_code === "domain_not_allowed"), "no refused domain");
  expect(failed.some((e) => e.reason_code === "code_invalid"), "no wrong code");
  expect(failed.some((e) => e.reason_code === "weak_password"), "no refused password");
  expect(failed.some((e) => e.reason_code === "email_taken"), "no address in use");
});

await step("the admin tab shows the settings and the count", async () => {
  await admin.page.goto(`${BASE}/admin/authentication`);
  await admin.page.getByRole("tab", { name: "Email sign-up" }).click();
  await admin.page.getByText("Accounts created in the last 30 days").waitFor({ timeout: 15_000 });
  const chip = admin.page.locator(".email-signup-settings__chip", { hasText: DOMAIN });
  expect((await chip.count()) === 1, "the domain is not listed");
  const checked = await admin.page.getByLabel("Allow people to create an account with their email").isChecked();
  expect(checked, "the switch is not on");
});

await step("on a phone the whole sign-up form can be reached", async () => {
  // 390 x 664: an iPhone with Safari's bars showing. The details step is the tallest.
  const phone = await browser.newContext({ viewport: { width: 390, height: 664 } });
  const small = await phone.newPage();
  await small.goto(`${BASE}/login`);
  await small.getByRole("button", { name: "Create an account" }).click();
  const address = `phone.${RUN}@${DOMAIN}`;
  const seen = mailbox.length;
  await small.locator("#signup-email").fill(address);
  await small.getByRole("button", { name: "Send code" }).click();
  const got = await codeFor(address, seen);
  await small.locator("#signup-code").fill(got.code);
  await small.getByRole("button", { name: "Verify" }).click();
  await small.locator("#signup-password").fill("x");
  const submit = small.getByRole("button", { name: "Create account" });
  // Scrolled the way a person scrolls: code could scroll even a box that hides its overflow.
  await small.mouse.move(195, 320);
  await small.mouse.wheel(0, 4000);
  await sleep(400);
  const box = await submit.boundingBox();
  expect(box && box.y >= 0 && box.y + box.height <= 664, `Create account is at ${JSON.stringify(box)}`);
  const legal = await small.locator(".login-page__legal").boundingBox();
  expect(!legal || !box || legal.y >= box.y + box.height || legal.y + legal.height <= box.y, "the trademark line lies over the button");
  const [scroll, width] = await small.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll <= width, `the page is ${scroll}px wide in a ${width}px window`);
  await phone.close();
});

// ── Put things back ──

if (savedSignup) {
  await api("/api/admin/authentication/email-signup", {
    method: "PUT",
    data: {
      enabled: savedSignup.enabled,
      allowed_domains: savedSignup.allowed_domains,
      default_plan_id: savedSignup.default_plan_id,
      reset_enabled: savedSignup.reset_enabled,
    },
  }).catch(() => undefined);
}
if (savedSmtp && !savedSmtp.password) {
  await api("/api/admin/smtp", { method: "PUT", data: { ...savedSmtp, password: null } }).catch(() => undefined);
} else if (!savedSmtp) {
  console.log(`  note  SMTP now points at the stopped sink on 127.0.0.1:${SMTP_PORT}; set it under Admin > SMTP Server`);
}
if (signedUp?.id) await api(`/api/admin/users/${signedUp.id}`, { method: "DELETE" }).catch(() => undefined);
await browser.close();
sink.close();

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} steps passed`);
process.exit(failed ? 1 : 0);
