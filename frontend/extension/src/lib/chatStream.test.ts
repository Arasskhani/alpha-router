/**
 * @vitest-environment node
 */
import { describe, expect, it, vi } from "vitest";

import { ChatStreamError, readChatStream } from "./chatStream";

/** A response whose body arrives in exactly these byte chunks. */
function streamOf(chunks: Array<string | Uint8Array>): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      controller.close();
    },
  });
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

const frame = (value: unknown) => `data: ${JSON.stringify(value)}\n\n`;
const text = (content: string) => frame({ choices: [{ delta: { content } }] });

describe("reading a chat stream", () => {
  it("puts the text together across chunk boundaries, even inside a character", async () => {
    const whole = text("سلام") + text(" world");
    const bytes = new TextEncoder().encode(whole);
    // Cut in the middle of a two-byte Persian letter and in the middle of a line.
    const cuts = [0, 17, 18, 40, bytes.length];
    const chunks = cuts.slice(1).map((end, i) => bytes.slice(cuts[i], end));
    const seen: string[] = [];
    const result = await readChatStream(streamOf(chunks), { onText: (full) => seen.push(full) });
    expect(result.text).toBe("سلام world");
    expect(seen.at(-1)).toBe("سلام world");
  });

  it("delivers a last line that has no newline", async () => {
    const result = await readChatStream(streamOf([text("a"), `data: ${JSON.stringify({ choices: [{ delta: { content: "b" } }] })}`]));
    expect(result.text).toBe("ab");
  });

  it("assembles tool calls from their fragments", async () => {
    const result = await readChatStream(
      streamOf([
        frame({ choices: [{ delta: { tool_calls: [{ index: 0, id: "call_a", type: "function", function: { name: "read_page", arguments: "" } }] } }] }),
        frame({ choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: '{"max_' } }] } }] }),
        frame({ choices: [{ delta: { tool_calls: [{ index: 1, id: "call_b", function: { name: "click", arguments: '{"ref":' } }] } }] }),
        frame({ choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: 'chars":500}' } }] } }] }),
        frame({ choices: [{ delta: { tool_calls: [{ index: 1, function: { arguments: '"e4"}' } }] } }] }),
      ]),
    );
    expect(result.toolCalls).toEqual([
      { id: "call_a", name: "read_page", arguments: '{"max_chars":500}' },
      { id: "call_b", name: "click", arguments: '{"ref":"e4"}' },
    ]);
  });

  it("collects the server's metadata", async () => {
    const onMeta = vi.fn();
    const result = await readChatStream(
      streamOf([text("hi"), frame({ alpha_router: { request_log_id: 42 } }), frame({ alpha_router: { budget_notice: "80%" } })]),
      { onMeta },
    );
    expect(result.meta).toEqual({ request_log_id: 42, budget_notice: "80%" });
    expect(onMeta).toHaveBeenCalledTimes(2);
  });

  it.each([
    [{ error: "Budget exceeded" }, "Budget exceeded"],
    [{ error: { message: "The provider is down" } }, "The provider is down"],
    [{ error: { code: 7 } }, "The model could not answer."],
  ])("stops on an error frame %o", async (errorFrame, message) => {
    await expect(readChatStream(streamOf([text("partial"), frame(errorFrame)]))).rejects.toEqual(new ChatStreamError(message));
  });

  it("skips [DONE], comments and lines that are not JSON", async () => {
    const result = await readChatStream(streamOf([": keep-alive\n\n", "data: not json\n\n", text("ok"), "data: [DONE]\n\n"]));
    expect(result).toEqual({ text: "ok", toolCalls: [], meta: {} });
  });

  it("keeps two calls apart that a provider sends under one index", async () => {
    const result = await readChatStream(
      streamOf([
        frame({ choices: [{ delta: { tool_calls: [{ index: 0, id: "a", function: { name: "read_page", arguments: "{}" } }] } }] }),
        frame({ choices: [{ delta: { tool_calls: [{ index: 0, id: "b", function: { name: "find", arguments: '{"query":"To"}' } }] } }] }),
      ]),
    );
    expect(result.toolCalls).toEqual([
      { id: "a", name: "read_page", arguments: "{}" },
      { id: "b", name: "find", arguments: '{"query":"To"}' },
    ]);
  });

  it("adds a fragment without an index to the call it continues", async () => {
    const result = await readChatStream(
      streamOf([
        frame({ choices: [{ delta: { tool_calls: [{ id: "a", function: { name: "type_text", arguments: '{"ref":"e1",' } }] } }] }),
        frame({ choices: [{ delta: { tool_calls: [{ function: { arguments: '"text":"hi"}' } }] } }] }),
      ]),
    );
    expect(result.toolCalls).toEqual([{ id: "a", name: "type_text", arguments: '{"ref":"e1","text":"hi"}' }]);
  });

  it("reads a whole answer sent at once rather than in pieces", async () => {
    const result = await readChatStream(
      streamOf([frame({ choices: [{ message: { content: "Done", tool_calls: [{ index: 0, id: "a", function: { name: "done", arguments: '{"summary":"ok"}' } }] }, finish_reason: "tool_calls" }] })]),
    );
    expect(result).toMatchObject({ text: "Done", toolCalls: [{ id: "a", name: "done" }] });
  });

  describe("strictly, for the agent", () => {
    it("takes a stream that ends with [DONE] or says why it finished", async () => {
      await expect(readChatStream(streamOf([text("a"), "data: [DONE]\n\n"]), {}, { strict: true })).resolves.toMatchObject({ text: "a" });
      await expect(readChatStream(streamOf([frame({ choices: [{ delta: { content: "b" }, finish_reason: "stop" }] })]), {}, { strict: true })).resolves.toMatchObject({ text: "b" });
    });

    it("refuses a stream that just stops, which asking again may mend", async () => {
      const err = await readChatStream(streamOf([text("half an ans")]), {}, { strict: true }).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ChatStreamError);
      expect((err as ChatStreamError).retryable).toBe(true);
      await expect(readChatStream(streamOf([]), {}, { strict: true })).rejects.toThrow(/cut short/);
    });

    it("refuses an answer cut at its length limit in the middle of an action, which asking again will not mend", async () => {
      const err = await readChatStream(
        streamOf([frame({ choices: [{ delta: { tool_calls: [{ index: 0, id: "a", function: { name: "type_text", arguments: '{"ref":"e1","te' } }] }, finish_reason: "length" }] }), "data: [DONE]\n\n"]),
        {},
        { strict: true },
      ).catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ChatStreamError);
      expect((err as ChatStreamError).retryable).toBe(false);
    });
  });
});
