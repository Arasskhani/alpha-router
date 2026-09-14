/**
 * Server-Sent Events reader for the chat completion stream.
 *
 * Pulled out of ChatPanel so it can be unit-tested. Three defects in the
 * inline version are fixed here:
 *  - a final `data:` line without a trailing newline (the last chunk of a
 *    stream, or a reply cut short by the server) was dropped, because only
 *    complete lines were processed and the leftover buffer was discarded;
 *  - `data:` immediately followed by the payload (no space) — legal per the
 *    SSE spec and emitted by some proxies — was ignored;
 *  - the underlying reader was never cancelled when the consumer stopped
 *    early (Stop button, thrown error), so the connection stayed open.
 */

const DATA_PREFIX = /^data:\s?/;

/** Split accumulated text into complete lines and the unterminated remainder. */
export function splitSseLines(buffer: string): { lines: string[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");
  const rest = lines.pop() ?? "";
  return { lines, rest };
}

/** Payload of a `data:` line, or null for comments/other fields/blank lines. */
export function parseSseDataLine(line: string): string | null {
  if (!DATA_PREFIX.test(line)) return null;
  return line.replace(DATA_PREFIX, "").trim();
}

/**
 * Yield every `data:` payload from a byte stream, including one left in the
 * buffer when the stream ends. Cancels the reader when iteration stops early.
 */
export async function* readSseEvents(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  decoder: TextDecoder = new TextDecoder(),
): AsyncGenerator<string, void, undefined> {
  let buffer = "";
  let finished = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        finished = true;
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const { lines, rest } = splitSseLines(buffer);
      buffer = rest;
      for (const line of lines) {
        const payload = parseSseDataLine(line);
        if (payload !== null && payload !== "") yield payload;
      }
    }
    // Flush the decoder and whatever line had no trailing newline.
    buffer += decoder.decode();
    for (const line of buffer.split("\n")) {
      const payload = parseSseDataLine(line);
      if (payload !== null && payload !== "") yield payload;
    }
  } finally {
    if (!finished) {
      try {
        await reader.cancel();
      } catch {
        // The stream may already be closed; nothing to release.
      }
    }
  }
}
