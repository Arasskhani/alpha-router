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

/**
 * Start the server on 127.0.0.1:port (0 picks a free one). `plantBase` is
 * where the planted images point: somewhere the check watches for requests.
 */
export async function startMockLlm({ port = 0, plantBase = "https://planted.invalid" } = {}) {
  const requests = [];
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
        requests.push({ model: body.model, stream: Boolean(body.stream), messages });
        const reply = replyFor(messages, plantBase);
        const id = `chatcmpl-e2e-${requests.length}`;
        const created = Math.floor(Date.now() / 1000);
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
    close: () => new Promise((resolve) => server.close(() => resolve())),
  };
}
