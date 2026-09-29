/**
 * Chat memory end-to-end check: a developer check against a running build
 * (npm run build, served by the backend), not part of CI.
 *
 * It drives Chromium through the web chat and reads what each turn sends to
 * /api/chat/completions (the request is answered here, so no model is used):
 *
 *   - a chat reopened from the list goes to the model whole, however long it
 *     is (the app loads a chat's latest page only, and used to send just that);
 *   - after a Stop, the next turn still carries the whole chat.
 *
 * Run it from frontend/ against a development stack:
 *
 *   CHAT_E2E_USER=admin CHAT_E2E_PASSWORD=... npm run e2e:chat-memory
 *
 *   CHAT_E2E_URL        app URL (default http://127.0.0.1:8080)
 *   CHAT_E2E_USER       an account without two-factor sign-in (required)
 *   CHAT_E2E_PASSWORD   its password (required)
 *   CHAT_E2E_CHROMIUM   optional path to a Chromium executable
 *
 * It makes a few chats in the account and deletes them at the end.
 * Exit codes: 0 every step passed, 1 a step failed, 2 bad configuration or setup.
 */
import process from "node:process";

const { chromium } = await import("playwright");

/* global console, setTimeout */

const BASE = (process.env.CHAT_E2E_URL || "http://127.0.0.1:8080").replace(/\/+$/, "");
const USER = process.env.CHAT_E2E_USER;
const PASSWORD = process.env.CHAT_E2E_PASSWORD;
if (!USER || !PASSWORD) {
  console.error("chat-memory-e2e: set CHAT_E2E_USER and CHAT_E2E_PASSWORD to an account without two-factor sign-in");
  process.exit(2);
}

const FIRST = "My workout plan: squats on Monday, running on Wednesday.";
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const results = [];
const created = [];

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

const browser = await chromium.launch(process.env.CHAT_E2E_CHROMIUM ? { executablePath: process.env.CHAT_E2E_CHROMIUM } : {});
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();

let headers;
try {
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Username", { exact: true }).fill(USER);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 20_000 });
  const csrf = (await context.cookies()).find((c) => c.name.includes("csrf"))?.value;
  headers = { "X-CSRF-Token": csrf, "Content-Type": "application/json" };
} catch (err) {
  console.error(`chat-memory-e2e: could not sign in at ${BASE}/login as ${USER}: ${String(err?.message || err).split("\n")[0]}`);
  await browser.close();
  process.exit(2);
}

const models = await (await page.request.get(`${BASE}/api/chat/models`)).json().catch(() => []);
const model = Array.isArray(models) && models[0]?.id;
if (!model) {
  console.error("chat-memory-e2e: the account has no chat model to open a chat with");
  await browser.close();
  process.exit(2);
}

/** A chat of `count` messages, its first one FIRST; its title is unique to this run. */
async function seedChat(count) {
  const title = `Chat memory check ${count} ${Date.now().toString(36)}`;
  const made = await (await page.request.post(`${BASE}/api/user/chats/sessions`, { headers, data: { title, model, titleLocked: true } })).json();
  created.push(made.id);
  const start = Date.now() - count * 60_000;
  const messages = [];
  for (let i = 0; i < count; i += 1) {
    const user = i % 2 === 0;
    messages.push({
      role: user ? "user" : "assistant",
      content: i === 0 ? FIRST : `${user ? "Question" : "Answer"} ${i}`,
      clientMessageId: `chat-memory-${made.id}-${i}`,
      ...(user ? { sentAt: start + i * 60_000 } : { receivedAt: start + i * 60_000, modelId: model }),
    });
  }
  const posted = await page.request.post(`${BASE}/api/user/chat-sessions/${made.id}/messages`, { headers, data: { messages } });
  expect(posted.ok(), `seeding the chat answered ${posted.status()}`);
  return title;
}

/** Each /api/chat/completions body, answered at once with a short reply - or held until released. */
const sent = [];
let holdNext = false;
let release = null;
await page.route("**/api/chat/completions", async (route) => {
  sent.push(JSON.parse(route.request().postData() || "{}"));
  if (holdNext) {
    holdNext = false;
    await new Promise((done) => {
      release = done;
    });
    await route.abort().catch(() => undefined);
    return;
  }
  await route.fulfill({
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    body: 'data: {"choices":[{"delta":{"content":"Noted."}}]}\n\ndata: [DONE]\n\n',
  });
});

async function openChat(title) {
  await page.goto(`${BASE}/admin/chat`);
  await page.getByText(title).first().click({ timeout: 20_000 });
  await sleep(1500);
}

async function send(text) {
  const before = sent.length;
  const box = page.locator("textarea").first();
  await box.fill(text);
  await box.press("Enter");
  for (let i = 0; i < 100 && sent.length === before; i += 1) await sleep(100);
  expect(sent.length > before, "no request reached /api/chat/completions");
  return sent.at(-1);
}

function whole(body, count, extra) {
  const messages = body.messages || [];
  const first = messages.find((m) => m.role !== "system");
  const text = typeof first?.content === "string" ? first.content : JSON.stringify(first?.content);
  expect(text === FIRST, `the model's history starts with ${JSON.stringify(String(text).slice(0, 40))}, not the chat's first message`);
  expect(messages.filter((m) => m.role !== "system").length === count + extra, `the model got ${messages.length} messages for a chat of ${count} and ${extra} new`);
  return `${messages.length} messages`;
}

console.log(`Chat memory end-to-end check against ${BASE}\n`);

for (const count of [40, 60, 200]) {
  await step(`a chat of ${count} messages reopened from the list goes to the model whole`, async () => {
    const title = await seedChat(count);
    await openChat(title);
    return whole(await send("What was my workout plan?"), count, 1);
  });
}

await step("after a Stop, the next turn still carries the whole chat", async () => {
  const title = await seedChat(60);
  await openChat(title);
  holdNext = true;
  await send("Tell me a long story.");
  await page.getByRole("button", { name: "Stop generating" }).click({ timeout: 10_000 });
  release?.();
  await sleep(2500);
  const body = await send("What was my workout plan?");
  const messages = (body.messages || []).filter((m) => m.role !== "system");
  const firstText = messages[0]?.content;
  expect(firstText === FIRST, `after the Stop the history starts with ${JSON.stringify(String(firstText).slice(0, 40))}`);
  // The stopped prompt never reached the server here (the request is answered in this script), so it may be gone.
  expect(messages.length >= 61, `after the Stop the model got ${messages.length} messages for a chat of 60 and 1 new`);
  return `${messages.length} messages`;
});

for (const id of created) {
  await page.request.delete(`${BASE}/api/user/chats/sessions/${id}`, { headers }).catch(() => undefined);
}
await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(failed.length ? `\n${failed.length} of ${results.length} steps failed.` : `\nAll ${results.length} steps passed.`);
process.exit(failed.length ? 1 : 0);
