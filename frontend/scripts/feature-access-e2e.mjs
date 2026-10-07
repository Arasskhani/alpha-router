/**
 * Feature Access end-to-end check: a developer check against a running build
 * (npm run build, served by the backend), not part of CI.
 *
 * An administrator closes the web Chat, then Projects, for a throwaway user on
 * the Feature Access page, and the user's side is checked in a second browser:
 *
 *   - the page is under Chat experience; a rule is added with the user picker,
 *     listed, and explained by "Check a user";
 *   - Chat closed: the user starts in Projects, the menu has no Chat, /app/chat
 *     says it is not enabled, and the server refuses the personal chat (403,
 *     feature_not_enabled) - while a turn in a team project's chat is answered;
 *   - Chat closed also closes Create projects: no New project button, and the
 *     server refuses creating one - until a personal Allow on Create projects;
 *   - the chat of a project that is the user's alone follows Chat: its Chats
 *     tab says so and the server refuses it, while its rooms keep working;
 *   - Browser extension closed: the server says the extension is not permitted;
 *   - Projects closed as well: the user starts in Media and /app/projects says
 *     it is not enabled; the server refuses /api/projects;
 *   - API keys closed: no new personal key, and the user's key is refused at
 *     the gateway (kept: it works again when the section opens);
 *   - both rules removed on the page: Chat is back;
 *   - the page fits a phone's width.
 *
 * Run it from frontend/ against a development stack with a chat model:
 *
 *   FA_E2E_USER=admin FA_E2E_PASSWORD=... node scripts/feature-access-e2e.mjs
 *
 *   FA_E2E_URL        app URL (default http://127.0.0.1:8080)
 *   FA_E2E_USER       an administrator without two-factor sign-in (required)
 *   FA_E2E_PASSWORD   its password (required)
 *   FA_E2E_CHROMIUM   optional path to a Chromium executable
 *
 * It creates one user, and removes its rules and moves it to Deleted Users at the end.
 * Exit codes: 0 every step passed, 1 a step failed, 2 bad configuration or setup.
 */
import process from "node:process";

const { chromium } = await import("playwright");

/* global console, setTimeout */

const BASE = (process.env.FA_E2E_URL || "http://127.0.0.1:8080").replace(/\/+$/, "");
const ADMIN = process.env.FA_E2E_USER;
const ADMIN_PASSWORD = process.env.FA_E2E_PASSWORD;
if (!ADMIN || !ADMIN_PASSWORD) {
  console.error("feature-access-e2e: set FA_E2E_USER and FA_E2E_PASSWORD to an administrator without two-factor sign-in");
  process.exit(2);
}

const RUN = Date.now().toString(36);
const USERNAME = `fa-check-${RUN}`;
// Must meet the password policy, which refuses one that contains the username.
const PASSWORD = `Zq-${RUN}-Passw0rd!`;
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

const browser = await chromium.launch(process.env.FA_E2E_CHROMIUM ? { executablePath: process.env.FA_E2E_CHROMIUM } : {});

async function signIn(username, password) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 20_000 });
  const csrf = (await context.cookies()).find((c) => c.name.includes("csrf"))?.value;
  return { context, page, headers: { "X-CSRF-Token": csrf, "Content-Type": "application/json" } };
}

let admin;
let userId;
// A project of the administrator's with the user in it: its chat follows Projects.
let teamProjectId;
try {
  admin = await signIn(ADMIN, ADMIN_PASSWORD);
  // A plan, so the user's project turn is not refused for its budget.
  let plans = await (await admin.page.request.get(`${BASE}/api/admin/plans`)).json();
  if (!Array.isArray(plans) || plans.length === 0) {
    await admin.page.request.post(`${BASE}/api/admin/plans`, {
      headers: admin.headers,
      data: { name: "Feature Access check", monthly_budget_usd: 5 },
    });
    plans = await (await admin.page.request.get(`${BASE}/api/admin/plans`)).json();
  }
  const made = await admin.page.request.post(`${BASE}/api/admin/users`, {
    headers: admin.headers,
    data: {
      username: USERNAME,
      email: `${USERNAME}@example.com`,
      password: PASSWORD,
      display_name: `FA Check ${RUN}`,
      plan_id: plans[0]?.id ?? null,
    },
  });
  expect(made.ok(), `creating the check user answered ${made.status()}: ${(await made.text()).slice(0, 200)}`);
  const body = await made.json();
  userId = body.id ?? body.user?.id;
  expect(userId, "the new user has no id");
  const team = await admin.page.request.post(`${BASE}/api/projects`, {
    headers: admin.headers,
    data: { name: `FA team ${RUN}` },
  });
  expect(team.ok(), `creating the team project answered ${team.status()}`);
  teamProjectId = (await team.json()).id;
  const joined = await admin.page.request.post(`${BASE}/api/projects/${teamProjectId}/members`, {
    headers: admin.headers,
    data: { userId, role: "contributor" },
  });
  expect(joined.ok(), `adding the user to the team project answered ${joined.status()}`);
} catch (err) {
  console.error(`feature-access-e2e: setup failed: ${String(err?.message || err).split("\n")[0]}`);
  await browser.close();
  process.exit(2);
}

const api = (path, init = {}) => admin.page.request.fetch(`${BASE}${path}`, { headers: admin.headers, ...init });

async function rules() {
  const data = await (await api("/api/admin/feature-access")).json();
  return data.features.flatMap((f) => f.rules);
}

let person;

await step("the page is under Chat experience", async () => {
  await admin.page.goto(`${BASE}/admin/feature-access`);
  await admin.page.getByRole("heading", { name: "Feature Access", level: 1 }).waitFor({ timeout: 20_000 });
  const link = admin.page.getByRole("link", { name: "Feature Access" }).first();
  expect(await link.isVisible(), "no Feature Access link in the admin menu");
  await admin.page.locator(".feature-access-section__head").first().waitFor({ timeout: 20_000 });
  for (const name of ["Chat", "Projects", "Create projects", "API keys", "Browser extension"]) {
    const heading = admin.page.getByRole("heading", { name, level: 2, exact: true });
    const section = admin.page.locator("section", { has: heading });
    // A stack may hold rules already: the section says who it is open to either way.
    expect((await section.textContent()).includes("Open to everyone"), `${name} does not say who it is open to`);
  }
});

await step("an administrator closes Chat for one user on the page", async () => {
  const chat = admin.page.locator("section", {
    has: admin.page.getByRole("heading", { name: "Chat", level: 2, exact: true }),
  });
  await chat.getByRole("button", { name: "Add rule" }).click();
  await admin.page.locator("#feature-access-user").fill(USERNAME);
  await admin.page.locator(".user-owner-select__item", { hasText: `FA Check ${RUN}` }).first().click({ timeout: 10_000 });
  await admin.page.locator("#feature-access-note").fill("e2e check");
  await admin.page.getByRole("button", { name: "Save rule" }).click();
  await admin.page.getByText(`Chat: denied for FA Check ${RUN}.`).waitFor({ timeout: 10_000 });
  const row = chat.locator("tbody tr", { hasText: `FA Check ${RUN}` });
  expect((await row.textContent()).includes("Denied"), "the rule is not listed as Denied");
});

await step("Check a user says which rule decided", async () => {
  await admin.page.locator("#feature-access-check-user").fill(USERNAME);
  await admin.page.locator(".user-owner-select__item", { hasText: `FA Check ${RUN}` }).first().click({ timeout: 10_000 });
  const result = admin.page.locator(".feature-access-check");
  await result.waitFor({ timeout: 10_000 });
  const text = await result.textContent();
  expect(text.includes("Closed") && text.includes("Denied for this person."), `check said: ${text}`);
});

await step("with Chat closed the user starts in Projects, without a Chat menu", async () => {
  person = await signIn(USERNAME, PASSWORD);
  await person.page.waitForURL(/\/app\/projects/, { timeout: 15_000 });
  const names = await person.page.locator("nav a").allTextContents();
  expect(!names.some((n) => n.trim() === "Chat"), `the menu still has Chat: ${names.join(", ")}`);
  expect(names.some((n) => n.trim() === "Projects"), "the menu has no Projects");
});

await step("/app/chat says Chat isn't enabled, and the server refuses it", async () => {
  await person.page.goto(`${BASE}/app/chat`);
  await person.page.getByRole("heading", { name: "Chat isn't enabled for you" }).waitFor({ timeout: 15_000 });
  const listed = await person.page.request.get(`${BASE}/api/user/chats`);
  expect(listed.status() === 403, `the chat list answered ${listed.status()}`);
  expect((await listed.json()).detail?.code === "feature_not_enabled", "the refusal has no feature_not_enabled code");
  const turn = await person.page.request.post(`${BASE}/api/chat/completions`, {
    headers: person.headers,
    data: { model: "any", messages: [{ role: "user", content: "hi" }] },
  });
  expect(turn.status() === 403, `a personal turn answered ${turn.status()}`);
});

await step("a team project's chat still answers", async () => {
  const models = await (await person.page.request.get(`${BASE}/api/chat/models`)).json();
  const model = Array.isArray(models) && models[0]?.id;
  expect(model, "the user has no chat model");
  const project = { id: teamProjectId };
  const chat = await (
    await person.page.request.post(`${BASE}/api/projects/${project.id}/chats`, {
      headers: person.headers,
      data: { title: "Project chat", model },
    })
  ).json();
  const turn = await person.page.request.post(`${BASE}/api/chat/completions`, {
    headers: person.headers,
    data: {
      model,
      messages: [{ role: "user", content: "hello from the project" }],
      chat_session_id: chat.id,
      project_id: project.id,
      // As the web app sends a project turn: saved in the project chat.
      persist_chat: true,
    },
  });
  expect(turn.status() === 200, `the project turn answered ${turn.status()}: ${(await turn.text()).slice(0, 160)}`);
  // And through the page itself: a message typed in a new project chat is answered, not refused.
  await person.page.goto(`${BASE}/app/projects/${project.id}`);
  const box = person.page.locator("textarea").first();
  await box.waitFor({ timeout: 20_000 });
  await sleep(1500); // the composer settles on the project chat and its model first
  const answered = person.page.waitForResponse((r) => r.url().endsWith("/api/chat/completions"), { timeout: 30_000 });
  await box.fill("hello from the page");
  await box.press("Enter");
  const response = await answered;
  expect(response.status() === 200, `the page's project turn answered ${response.status()}`);
  return `model ${model}`;
});

let soloProjectId = null;

await step("Chat closed closes Create projects: no New project, and the server refuses it", async () => {
  await person.page.goto(`${BASE}/app/projects`);
  await person.page
    .getByText("Creating projects isn't enabled for your account. You can still work in projects you're invited to.")
    .waitFor({ timeout: 15_000 });
  expect(!(await person.page.getByRole("button", { name: "+ New project" }).isVisible()), "New project is offered");
  const made = await person.page.request.post(`${BASE}/api/projects`, {
    headers: person.headers,
    data: { name: `FA solo ${RUN}` },
  });
  expect(made.status() === 403, `creating a project answered ${made.status()}`);
  expect((await made.json()).detail?.feature === "project_create", "the refusal is not for Create projects");
  const check = await (await api(`/api/admin/feature-access/check?user_id=${userId}`)).json();
  const create = check.features.find((f) => f.feature === "project_create");
  expect(create && !create.allowed && create.reason === "chat_closed", `Check a user said ${JSON.stringify(create)}`);
});

await step("a personal Allow on Create projects lets the user create one", async () => {
  const added = await api("/api/admin/feature-access/rules", {
    method: "POST",
    data: { feature: "project_create", target_type: "user", target: userId, effect: "allow" },
  });
  expect(added.status() === 201, `adding the Allow answered ${added.status()}`);
  const ruleId = (await added.json()).id;
  try {
    await person.page.goto(`${BASE}/app/projects`);
    await person.page.getByRole("button", { name: "+ New project" }).waitFor({ timeout: 15_000 });
    const made = await person.page.request.post(`${BASE}/api/projects`, {
      headers: person.headers,
      data: { name: `FA solo ${RUN}` },
    });
    expect(made.status() === 201, `creating a project answered ${made.status()}`);
    soloProjectId = (await made.json()).id;
  } finally {
    await api(`/api/admin/feature-access/rules/${ruleId}`, { method: "DELETE" });
  }
});

await step("the chat of a project that is the user's alone follows Chat", async () => {
  expect(soloProjectId, "no project of the user's own to check");
  const project = await (await person.page.request.get(`${BASE}/api/projects/${soloProjectId}`)).json();
  expect(project.chatClosed === true, `the project says chatClosed ${project.chatClosed}`);
  const chats = await person.page.request.get(`${BASE}/api/projects/${soloProjectId}/chats`);
  expect(chats.status() === 403, `its chats answered ${chats.status()}`);
  expect((await chats.json()).detail?.reason === "solo_project", "the refusal is not the solo-project one");
  const refusedOnPage = [];
  person.page.on("response", (r) => {
    if (r.status() === 403 && r.url().includes(`/api/projects/${soloProjectId}/chats`)) refusedOnPage.push(r.url());
  });
  await person.page.goto(`${BASE}/app/projects/${soloProjectId}`);
  await person.page.getByText("so chat is closed in projects that only you are in").waitFor({ timeout: 15_000 });
  await sleep(1500);
  expect(refusedOnPage.length === 0, `the page asked for the closed chats: ${refusedOnPage.length} refusals`);
  const rooms = await person.page.request.get(`${BASE}/api/projects/${soloProjectId}/rooms`);
  expect(rooms.status() === 200, `its rooms answered ${rooms.status()}`);
  // Rooms work, but a decision cannot be handed to the closed chat.
  const room = await person.page.request.post(`${BASE}/api/projects/${soloProjectId}/rooms`, {
    headers: person.headers,
    data: { title: "Notes" },
  });
  expect(room.ok(), `creating a room answered ${room.status()}`);
  await person.page.getByRole("button", { name: "Rooms", exact: true }).click();
  await person.page.getByRole("heading", { name: "Notes", level: 3 }).waitFor({ timeout: 15_000 });
  expect(
    !(await person.page.getByRole("button", { name: "Send decision to Chat" }).isVisible()),
    "the room offers to send a decision to the closed chat",
  );
});

await step("Browser extension closed: the server says the extension is not permitted", async () => {
  const before = await (await person.page.request.get(`${BASE}/api/extension/info`)).json();
  const added = await api("/api/admin/feature-access/rules", {
    method: "POST",
    data: { feature: "extension", target_type: "user", target: userId },
  });
  expect(added.status() === 201, `adding the extension rule answered ${added.status()}`);
  const ruleId = (await added.json()).id;
  try {
    const info = await (await person.page.request.get(`${BASE}/api/extension/info`)).json();
    expect(info.permitted === false, `the extension is still permitted (it was ${before.permitted} before)`);
    const session = await (await person.page.request.get(`${BASE}/api/auth/session`)).json();
    expect(session.features?.extension === false, "the session still offers the extension");
  } finally {
    await api(`/api/admin/feature-access/rules/${ruleId}`, { method: "DELETE" });
  }
});

await step("API keys closed: no new key, and the key the user has is refused, then works again", async () => {
  let keyId = null;
  let ruleId = null;
  try {
    const made = await person.page.request.post(`${BASE}/api/user/api-keys`, {
      headers: person.headers,
      data: { name: "FA check" },
    });
    expect(made.ok(), `making a personal key answered ${made.status()}`);
    const created = await made.json();
    keyId = created.id;
    const bearer = { Authorization: `Bearer ${created.api_key}` };
    const before = await person.page.request.get(`${BASE}/v1/models`, { headers: bearer });
    expect(before.status() === 200, `the key answered ${before.status()} before`);
    const added = await api("/api/admin/feature-access/rules", {
      method: "POST",
      data: { feature: "api_keys", target_type: "user", target: userId },
    });
    expect(added.status() === 201, `adding the API keys rule answered ${added.status()}`);
    ruleId = (await added.json()).id;
    const refused = await person.page.request.get(`${BASE}/v1/models`, { headers: bearer });
    expect(refused.status() === 403, `the key answered ${refused.status()} while closed`);
    expect((await refused.json()).detail?.code === "feature_not_enabled", "the refusal has no feature_not_enabled code");
    const another = await person.page.request.post(`${BASE}/api/user/api-keys`, {
      headers: person.headers,
      data: { name: "Another" },
    });
    expect(another.status() === 403, `making a key while closed answered ${another.status()}`);
    await api(`/api/admin/feature-access/rules/${ruleId}`, { method: "DELETE" });
    ruleId = null;
    const again = await person.page.request.get(`${BASE}/v1/models`, { headers: bearer });
    expect(again.status() === 200, `the key answered ${again.status()} after the section opened`);
  } finally {
    // Nothing of this step is left behind, whatever failed: the rule, then the key.
    if (ruleId) await api(`/api/admin/feature-access/rules/${ruleId}`, { method: "DELETE" }).catch(() => undefined);
    if (keyId) {
      await person.page.request
        .delete(`${BASE}/api/user/api-keys/${keyId}`, { headers: person.headers })
        .catch(() => undefined);
    }
  }
});

await step("with Projects closed too the user starts in Media", async () => {
  const added = await api("/api/admin/feature-access/rules", {
    method: "POST",
    data: { feature: "projects", target_type: "user", target: userId },
  });
  expect(added.status() === 201, `adding the Projects rule answered ${added.status()}`);
  await person.page.goto(`${BASE}/`);
  await person.page.waitForURL(/\/app\/media/, { timeout: 15_000 });
  await person.page.goto(`${BASE}/app/projects`);
  await person.page.getByRole("heading", { name: "Projects isn't enabled for you" }).waitFor({ timeout: 15_000 });
  const listed = await person.page.request.get(`${BASE}/api/projects`);
  expect(listed.status() === 403, `the project list answered ${listed.status()}`);
});

await step("removing both rules on the page gives Chat back", async () => {
  await admin.page.goto(`${BASE}/admin/feature-access`);
  for (let i = 0; i < 2; i += 1) {
    await admin.page.getByRole("button", { name: new RegExp(`Remove the rule for FA Check ${RUN}`) }).first().click();
    await admin.page.locator(".btn-danger", { hasText: "Remove" }).click();
    await admin.page.getByText(`Rule for FA Check ${RUN} removed.`).waitFor({ timeout: 10_000 });
    await sleep(300);
  }
  expect((await rules()).every((r) => r.target !== userId), "a rule for the user is left");
  await person.page.goto(`${BASE}/`);
  await person.page.waitForURL(/\/app\/chat/, { timeout: 15_000 });
  const listed = await person.page.request.get(`${BASE}/api/user/chats`);
  expect(listed.status() === 200, `the chat list answered ${listed.status()}`);
});

await step("the page fits a phone", async () => {
  await admin.page.setViewportSize({ width: 390, height: 844 });
  await admin.page.goto(`${BASE}/admin/feature-access`);
  await admin.page.getByRole("heading", { name: "Feature Access", level: 1 }).waitFor({ timeout: 20_000 });
  await sleep(500);
  const [scroll, width] = await admin.page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll <= width, `the page is ${scroll}px wide in a ${width}px window`);
});

// Clean up whatever is left: the user's rules, then the user.
for (const rule of await rules().catch(() => [])) {
  if (rule.target === userId && rule.target_type === "user") {
    await api(`/api/admin/feature-access/rules/${rule.id}`, { method: "DELETE" }).catch(() => undefined);
  }
}
for (const [id, owner] of [
  [soloProjectId, person],
  [teamProjectId, admin],
]) {
  if (id && owner) {
    await owner.page.request.delete(`${BASE}/api/projects/${id}`, { headers: owner.headers }).catch(() => undefined);
  }
}
await api(`/api/admin/users/${userId}`, { method: "DELETE" }).catch(() => undefined);
await browser.close();

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} steps passed`);
process.exit(failed ? 1 : 0);
