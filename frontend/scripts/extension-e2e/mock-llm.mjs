/**
 * A tiny OpenAI-compatible model server for the extension end-to-end check.
 *
 * It answers from what it was sent, so the check can tell what reached the
 * model: a question that comes with a shared page is answered with the page's
 * title (read from the <untrusted_page_content title="…"> wrapper), anything
 * else with a fixed line. Every request is kept for the check to inspect.
 */
import http from "node:http";

export const MOCK_MODEL = "extension-e2e-echo";
const PLAIN_REPLY = "Hello from the extension check's mock model.";

function titleOf(messages) {
  for (const message of messages) {
    const content = typeof message.content === "string" ? message.content : "";
    const match = /<untrusted_page_content [^>]*title="([^"]*)"/.exec(content);
    if (match) return match[1].replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  }
  return null;
}

/** What the mock answers to a request's messages. */
function replyFor(messages) {
  const title = titleOf(messages);
  if (title !== null) return `The page is titled “${title}”.`;
  // The chat title helper asks for a short title; any short answer will do.
  if (messages.some((m) => m.role === "system" && typeof m.content === "string" && /\btitles?\b/i.test(m.content))) {
    return "Extension check";
  }
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

/** Start the server on 127.0.0.1:port (0 picks a free one). */
export async function startMockLlm({ port = 0 } = {}) {
  const requests = [];
  const server = http.createServer(async (req, res) => {
    try {
      if (req.method === "GET" && req.url?.endsWith("/models")) {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ object: "list", data: [{ id: MOCK_MODEL, object: "model", created: 1_700_000_000, owned_by: "e2e" }] }));
        return;
      }
      if (req.method === "POST" && req.url?.endsWith("/chat/completions")) {
        const body = JSON.parse((await readBody(req)) || "{}");
        const messages = Array.isArray(body.messages) ? body.messages : [];
        requests.push({ model: body.model, stream: Boolean(body.stream), messages });
        const text = replyFor(messages);
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
              choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }],
              usage: USAGE,
            }),
          );
          return;
        }
        res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
        const pieces = text.match(/.{1,12}/gsu) ?? [text];
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
