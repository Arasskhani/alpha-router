/**
 * Chat memory end-to-end check: a developer check against a running build
 * (npm run build, served by the backend), not part of CI.
 *
 * It drives Chromium through the web chat and reads what each turn sends to
 * /api/chat/completions (the request is answered here, so no model is used):
 *
 *   - a chat reopened from the list holds its latest page; each turn sends that
 *     page and says where it starts (history_from_sequence), and the server puts
 *     the older messages in front (backend/tests/test_chat_history_completion.py);
 *   - the turn starts at once: no older page is read before it;
 *   - after a Stop, the next turn still says where its history starts;
 *   - an answer the server fitted into the model's window says so under its
 *     label, and the label opens what that means;
 *   - an answer that read from earlier chats names them, each a link that opens
 *     it - one the chat list has not loaded too.
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

/** Reads of a chat's older pages (a messages request with `before`), as they happen. */
const olderReads = [];
page.on("request", (request) => {
  const url = request.url();
  if (request.method() === "GET" && /\/api\/user\/chat-sessions\/[^/]+\/messages\?/.test(url) && url.includes("before=")) {
    olderReads.push(url);
  }
});

/** Each /api/chat/completions body, answered at once with a short reply - or held until released. */
const sent = [];
let holdNext = false;
let release = null;
/** The server's trailing metadata for the next answer, when a step wants one. */
let nextTrailer = null;
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
  const trailer = nextTrailer ? `data: ${JSON.stringify({ alpha_router: nextTrailer })}\n\n` : "";
  nextTrailer = null;
  await route.fulfill({
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    body: `data: {"choices":[{"delta":{"content":"Noted."}}]}\n\n${trailer}data: [DONE]\n\n`,
  });
});

async function openChat(title) {
  await page.goto(`${BASE}/admin/chat`);
  await page.getByText(title).first().click({ timeout: 20_000 });
  await sleep(1500);
}

async function send(text) {
  const before = sent.length;
  olderReads.length = 0;
  const box = page.locator("textarea").first();
  await box.fill(text);
  await box.press("Enter");
  for (let i = 0; i < 100 && sent.length === before; i += 1) await sleep(100);
  expect(sent.length > before, "no request reached /api/chat/completions");
  return sent.at(-1);
}

/** The seeded message at a sequence, as seedChat wrote it. */
function seeded(sequence) {
  const i = sequence - 1;
  return i === 0 ? FIRST : `${i % 2 === 0 ? "Question" : "Answer"} ${i}`;
}

/**
 * The turn and the server together carry the whole chat: the turn's history
 * starts where history_from_sequence says (the chat's first message when it
 * says nothing), runs to the chat's last, and the server holds what is older.
 */
function wholeWithTheServer(body, count, extra) {
  const messages = (body.messages || []).filter((m) => m.role !== "system");
  const from = body.history_from_sequence ?? 1;
  const first = typeof messages[0]?.content === "string" ? messages[0].content : JSON.stringify(messages[0]?.content);
  expect(first === seeded(from), `the turn's history starts with ${JSON.stringify(String(first).slice(0, 40))}, not message ${from}`);
  expect(from - 1 + messages.length === count + extra, `the turn sent messages ${from} to ${from - 1 + messages.length} of a chat of ${count} and ${extra} new`);
  expect(olderReads.length === 0, `the turn waited on ${olderReads.length} reads of older pages`);
  return from > 1 ? `${messages.length} sent, the server adds ${from - 1}` : `${messages.length} sent, the whole chat`;
}

console.log(`Chat memory end-to-end check against ${BASE}\n`);

for (const count of [40, 60, 200]) {
  await step(`a chat of ${count} messages reopened from the list: the turn starts at once, and with the server has it all`, async () => {
    const title = await seedChat(count);
    await openChat(title);
    return wholeWithTheServer(await send("What was my workout plan?"), count, 1);
  });
}

await step("after a Stop, the next turn still says where its history starts", async () => {
  const title = await seedChat(60);
  await openChat(title);
  holdNext = true;
  await send("Tell me a long story.");
  await page.getByRole("button", { name: "Stop generating" }).click({ timeout: 10_000 });
  release?.();
  await sleep(2500);
  const body = await send("What was my workout plan?");
  const messages = (body.messages || []).filter((m) => m.role !== "system");
  const from = body.history_from_sequence ?? 1;
  expect(messages[0]?.content === seeded(from), `after the Stop the history starts with ${JSON.stringify(String(messages[0]?.content).slice(0, 40))}, not message ${from}`);
  // The stopped prompt never reached the server here (the request is answered in this script), so it may be gone.
  expect(from - 1 + messages.length >= 61, `after the Stop the turn and the server hold ${from - 1 + messages.length} messages of a chat of 60 and 1 new`);
  return `${messages.length} sent from message ${from}`;
});

await step("an answer fitted into the model's window says so under its label", async () => {
  const title = await seedChat(40);
  await openChat(title);
  nextTrailer = { context_fit: { dropped: 12, summarized: 10 } };
  await send("And now?");
  const label = page.locator(".alpha-router-msg-context-label").last();
  await label.waitFor({ timeout: 10_000 });
  const text = (await label.locator("summary").textContent()) || "";
  expect(text.includes("read as a summary; 2 more left out"), `the label reads ${JSON.stringify(text)}`);
  const note = label.locator(".alpha-router-msg-context-note");
  expect(!(await note.isVisible()), "the note is open before the label is");
  await label.locator("summary").click();
  await note.waitFor({ state: "visible", timeout: 5_000 });
  expect(((await note.textContent()) || "").includes("the 10 oldest were sent as a summary"), "the note does not say what was summarized");
  return text;
});

await step("an answer that read from an earlier chat names it, and the name opens it", async () => {
  const earlier = await seedChat(4);
  const earlierId = created.at(-1);
  const title = await seedChat(2);
  await openChat(title);
  nextTrailer = { recalled_chats: [{ id: earlierId, title: earlier }] };
  await send("What was my workout plan?");
  const label = page.locator(".alpha-router-msg-recall-label").last();
  await label.waitFor({ timeout: 10_000 });
  expect(((await label.textContent()) || "").startsWith("Read from 1 earlier chat"), "the label does not count the chat");
  expect((await page.getByText("Answer 3").count()) === 0, "the earlier chat is open already");
  await label.getByRole("button", { name: earlier }).click();
  // Only the earlier chat (four messages) has a third one.
  await page.getByText("Answer 3").first().waitFor({ timeout: 10_000 });
  return "opened";
});

await step("the name of an earlier chat the list has not loaded opens it too", async () => {
  const earlier = await seedChat(4);
  const earlierId = created.at(-1);
  const title = await seedChat(2);
  // The chat list is served without the earlier chat, as for one older than the days it loads.
  await page.route("**/api/user/chats?**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.sessions = (body.sessions || []).filter((row) => row.id !== earlierId);
    await route.fulfill({ response, json: body });
  });
  try {
    await openChat(title);
    expect((await page.getByText(earlier).count()) === 0, "the earlier chat is in the list");
    nextTrailer = { recalled_chats: [{ id: earlierId, title: earlier }] };
    await send("What was my workout plan?");
    const label = page.locator(".alpha-router-msg-recall-label").last();
    await label.waitFor({ timeout: 10_000 });
    const link = label.getByRole("button", { name: earlier });
    expect(await link.isEnabled(), "the name is a button that does nothing");
    await link.click();
    await page.getByText("Answer 3").first().waitFor({ timeout: 10_000 });
    return "read by id and opened";
  } finally {
    await page.unroute("**/api/user/chats?**");
  }
});

for (const id of created) {
  await page.request.delete(`${BASE}/api/user/chats/sessions/${id}`, { headers }).catch(() => undefined);
}
await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(failed.length ? `\n${failed.length} of ${results.length} steps failed.` : `\nAll ${results.length} steps passed.`);
process.exit(failed.length ? 1 : 0);
