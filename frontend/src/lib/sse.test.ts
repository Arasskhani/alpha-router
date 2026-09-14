import { describe, expect, it } from "vitest";
import { parseSseDataLine, readSseEvents, splitSseLines } from "./sse";

function streamOf(chunks: string[], { neverClose = false } = {}) {
  const encoder = new TextEncoder();
  let i = 0;
  let cancelled = false;
  const reader = {
    async read() {
      if (i < chunks.length) return { done: false as const, value: encoder.encode(chunks[i++]) };
      if (neverClose) return new Promise<never>(() => {});
      return { done: true as const, value: undefined };
    },
    async cancel() {
      cancelled = true;
    },
    releaseLock() {},
    closed: Promise.resolve(undefined),
  } as unknown as ReadableStreamDefaultReader<Uint8Array>;
  return { reader, isCancelled: () => cancelled };
}

async function collect(reader: ReadableStreamDefaultReader<Uint8Array>) {
  const out: string[] = [];
  for await (const p of readSseEvents(reader)) out.push(p);
  return out;
}

describe("sse", () => {
  it("parses data lines with and without the space, ignores comments", () => {
    expect(parseSseDataLine("data: {\"a\":1}")).toBe("{\"a\":1}");
    expect(parseSseDataLine("data:{\"a\":1}")).toBe("{\"a\":1}");
    expect(parseSseDataLine(": keep-alive")).toBeNull();
    expect(parseSseDataLine("event: ping")).toBeNull();
    expect(parseSseDataLine("")).toBeNull();
  });

  it("splits CRLF and LF and keeps the unterminated tail", () => {
    expect(splitSseLines("data: a\r\ndata: b\npartial")).toEqual({ lines: ["data: a", "data: b"], rest: "partial" });
  });

  it("delivers a final data line that has no trailing newline", async () => {
    const { reader } = streamOf(["data: one\n\ndata: two\n", "data: three"]);
    expect(await collect(reader)).toEqual(["one", "two", "three"]);
  });

  it("reassembles a payload split across chunks, including multi-byte characters", async () => {
    const text = 'data: {"t":"سلام دنیا"}\n';
    const bytes = new TextEncoder().encode(text);
    // Cut in the middle of a UTF-8 sequence.
    const encoderChunks = [bytes.slice(0, 14), bytes.slice(14)];
    let i = 0;
    const reader = {
      async read() {
        if (i < encoderChunks.length) return { done: false as const, value: encoderChunks[i++] };
        return { done: true as const, value: undefined };
      },
      async cancel() {},
    } as unknown as ReadableStreamDefaultReader<Uint8Array>;
    expect(await collect(reader)).toEqual(['{"t":"سلام دنیا"}']);
  });

  it("cancels the reader when the consumer stops early", async () => {
    const { reader, isCancelled } = streamOf(["data: a\ndata: b\n", "data: c\n"], { neverClose: true });
    for await (const p of readSseEvents(reader)) {
      if (p === "b") break;
    }
    expect(isCancelled()).toBe(true);
  });

  it("does not cancel a stream that finished on its own", async () => {
    const { reader, isCancelled } = streamOf(["data: a\n"]);
    await collect(reader);
    expect(isCancelled()).toBe(false);
  });
});
