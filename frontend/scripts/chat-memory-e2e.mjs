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
 *     it - one the chat list has not loaded too;
 *   - after an image turn (the image is answered here too), the next turn still
 *     says where its history starts, and holds the image exchange. It needs the
 *     Image Generation tool allowed for the account (Admin -> Chat tools).
 *
 * With CHAT_E2E_LIVE_RECALL=1 one more step runs against the stack itself, no
 * answer faked: a chat is stored, the knowledge worker indexes it (about a
 * minute after its reply), and a turn in a new chat - answered by the stack's
 * chat model - names it under the answer. It needs recall set up (Admin ->
 * Memory: an embedding model, Recall earlier chats on) and the knowledge worker
 * and scheduler running.
 *
 * Run it from frontend/ against a development stack:
 *
 *   CHAT_E2E_USER=admin CHAT_E2E_PASSWORD=... npm run e2e:chat-memory
 *
 *   CHAT_E2E_URL        app URL (default http://127.0.0.1:8080)
 *   CHAT_E2E_USER       an account without two-factor sign-in (required)
 *   CHAT_E2E_PASSWORD   its password (required)
 *   CHAT_E2E_CHROMIUM   optional path to a Chromium executable
 *   CHAT_E2E_LIVE_RECALL   1 to run the live recall step (see above)
 *   CHAT_E2E_RECALL_WAIT   seconds to wait for the index in that step (default 240)
 *   CHAT_E2E_LIVE_MODEL    the chat model that step's turn goes to (default: the first one offered)
 *
 * It makes a few chats in the account and deletes them at the end, with any
 * memory already learned from them (one learned later stays).
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

/** A chat of `count` messages, its first one FIRST (or the `texts` given); its title is unique to this run. */
async function seedChat(count, texts, chatModel = model) {
  const title = `Chat memory check ${count} ${Date.now().toString(36)}`;
  const made = await (
    await page.request.post(`${BASE}/api/user/chats/sessions`, { headers, data: { title, model: chatModel, titleLocked: true } })
  ).json();
  created.push(made.id);
  if (!count) return title;
  const start = Date.now() - count * 60_000;
  const messages = [];
  for (let i = 0; i < count; i += 1) {
    const user = i % 2 === 0;
    messages.push({
      role: user ? "user" : "assistant",
      content: texts?.[i] ?? (i === 0 ? FIRST : `${user ? "Question" : "Answer"} ${i}`),
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
/** The next turn goes to the stack itself (the live recall step). */
let liveNext = false;
/** The server's trailing metadata for the next answer, when a step wants one. */
let nextTrailer = null;
await page.route("**/api/chat/completions", async (route) => {
  sent.push(JSON.parse(route.request().postData() || "{}"));
  if (liveNext) {
    liveNext = false;
    await route.continue();
    return;
  }
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

/** The image model this check offers the chat (the image itself is answered here, so none is called). */
const IMAGE_MODEL = {
  id: "chat-memory-e2e-image",
  external_id: "chat-memory-e2e-image",
  name: "Chat memory check image model",
  provider: "openai",
  is_image_model: true,
  supports_text_to_image: true,
};

async function toggleImageTool() {
  await page.getByRole("button", { name: "Tools", exact: true }).click();
  const toggle = page.getByRole("button", { name: "Toggle Image Generation" });
  const shown = await toggle.waitFor({ timeout: 5_000 }).then(
    () => true,
    () => false,
  );
  expect(shown, "the Image Generation tool is not offered to this account (Admin -> Chat tools)");
  await toggle.click();
  await page.keyboard.press("Escape");
  await sleep(300);
}

await step("after an image turn, the next turn still says where its history starts, and holds the image", async () => {
  const title = await seedChat(60);
  const id = created.at(-1);
  let images = 0;
  await page.route("**/api/chat/models", async (route) => {
    const response = await route.fetch();
    const list = await response.json();
    await route.fulfill({ response, json: Array.isArray(list) ? [...list, IMAGE_MODEL] : list });
  });
  await page.route("**/api/images/generate", async (route) => {
    images += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: [{ url: `${BASE}/favicon.svg` }], model: IMAGE_MODEL.id }),
    });
  });
  try {
    await openChat(title);
    await toggleImageTool();
    const before = sent.length;
    const box = page.locator("textarea").first();
    await box.fill("Draw my workout plan as a poster");
    await box.press("Enter");
    for (let i = 0; i < 100 && images === 0; i += 1) await sleep(100);
    expect(images === 1, "the turn did not go to image generation");
    expect(sent.length === before, "the image turn went to the chat model");
    // Stored on the server: the prompt, then the image in place of its pending marker.
    let last = "";
    for (let i = 0; i < 60; i += 1) {
      const page_ = await (await page.request.get(`${BASE}/api/user/chat-sessions/${id}/messages?limit=2`)).json();
      last = String(page_.messages?.at(-1)?.content || "");
      if (last.startsWith("__ALPHA_ROUTER_IMAGE_JSON__:")) break;
      await sleep(250);
    }
    expect(last.startsWith("__ALPHA_ROUTER_IMAGE_JSON__:"), `the chat's last stored message is ${JSON.stringify(last.slice(0, 40))}`);
    await toggleImageTool();
    return wholeWithTheServer(await send("What was my workout plan?"), 60, 3);
  } finally {
    await page.unroute("**/api/chat/models");
    await page.unroute("**/api/images/generate");
  }
});

if (process.env.CHAT_E2E_LIVE_RECALL === "1") {
  await step("live: a new chat reads from an earlier one the knowledge worker indexed, and names it", async () => {
    const status = async () => (await page.request.get(`${BASE}/api/admin/memory/recall/status`)).json();
    const prefs = await (await page.request.get(`${BASE}/api/user/chats/prefs`)).json();
    expect(
      prefs.memory_enabled !== false && prefs.memory_recall_chats !== false,
      "the account has its memory or its earlier chats switched off (Settings -> Memory)",
    );
    let before = await status();
    expect(before.enabled, "recall is not set up here (Admin -> Memory: an embedding model, Recall earlier chats)");
    // What earlier steps queued settles first, so what this step waits for is its own chat.
    const settle = Date.now() + 120_000;
    while ((before.pending || before.running) && Date.now() < settle) {
      await sleep(5_000);
      before = await status();
    }
    const code = `lark-${Date.now().toString(36)}`;
    const earlier = await seedChat(2, [`My locker code is ${code}.`, `Noted: your locker code is ${code}.`]);
    const wait = Number(process.env.CHAT_E2E_RECALL_WAIT || 240) * 1000;
    const started = Date.now();
    let now = before;
    while (Date.now() < started + wait) {
      now = await status();
      if (now.chunks > before.chunks && !now.pending && !now.running) break;
      await sleep(5_000);
    }
    const indexedIn = Math.round((Date.now() - started) / 1000);
    expect(
      now.chunks > before.chunks,
      `nothing was indexed in ${wait / 1000}s: is the knowledge worker running, and the account's indexing budget left?`,
    );
    const title = await seedChat(0, undefined, process.env.CHAT_E2E_LIVE_MODEL || model);
    await openChat(title);
    liveNext = true;
    await send("What is my locker code?");
    const label = page.locator(".alpha-router-msg-recall-label").last();
    await label.waitFor({ timeout: 90_000 });
    const text = (await label.textContent()) || "";
    // Other chats of the account may be read too (this check's own among them); the one with the code must be.
    expect(text.startsWith("Read from") && text.includes(earlier), `the label reads ${JSON.stringify(text)}`);
    return `indexed in about ${indexedIn}s`;
  });
}

// Memories learned from this check's chats go with them (listed before the chats, which they name).
const learned = await (await page.request.get(`${BASE}/api/user/memories?limit=200`)).json().catch(() => ({}));
for (const memory of learned?.memories || []) {
  if (created.includes(memory.source_session_id)) {
    await page.request.delete(`${BASE}/api/user/memories/${memory.id}`, { headers }).catch(() => undefined);
  }
}
for (const id of created) {
  await page.request.delete(`${BASE}/api/user/chats/sessions/${id}`, { headers }).catch(() => undefined);
}
await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(failed.length ? `\n${failed.length} of ${results.length} steps failed.` : `\nAll ${results.length} steps passed.`);
process.exit(failed.length ? 1 : 0);
