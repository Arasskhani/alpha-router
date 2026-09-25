/**
 * Read a /api/chat/completions stream: text, tool calls, metadata and errors.
 *
 * The server streams OpenAI-shaped chunks (`choices[0].delta`), its own
 * metadata frames (`alpha_router`: request log id, budget notice) and error
 * frames (`error`). Tool calls arrive as fragments keyed by index - the id and
 * name once, the arguments in pieces - and are put back together here.
 * The SSE framing itself is the web app's reader (src/lib/sse.ts).
 */

import { readSseEvents } from "../../../src/lib/sse";

type ToolCall = { id: string; name: string; arguments: string };

export type StreamResult = {
  text: string;
  toolCalls: ToolCall[];
  meta: Record<string, unknown>;
};

export type StreamHandlers = {
  onText?: (full: string) => void;
  onMeta?: (meta: Record<string, unknown>) => void;
};

export class ChatStreamError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChatStreamError";
  }
}

type ToolCallFragment = {
  index?: number;
  id?: string;
  function?: { name?: string; arguments?: string };
};

function errorText(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object" && typeof (error as { message?: unknown }).message === "string") {
    return (error as { message: string }).message;
  }
  return "The model could not answer.";
}

export async function readChatStream(response: Response, handlers: StreamHandlers = {}): Promise<StreamResult> {
  if (!response.body) throw new ChatStreamError("The server sent no reply.");
  let text = "";
  const meta: Record<string, unknown> = {};
  const calls = new Map<number, ToolCall>();
  for await (const payload of readSseEvents(response.body.getReader())) {
    if (payload === "[DONE]") continue;
    let frame: Record<string, unknown>;
    try {
      frame = JSON.parse(payload) as Record<string, unknown>;
    } catch {
      continue; // A keep-alive or a line some proxy added.
    }
    if (frame.error) throw new ChatStreamError(errorText(frame.error));
    const extra = frame.alpha_router;
    if (extra && typeof extra === "object") {
      Object.assign(meta, extra);
      handlers.onMeta?.(extra as Record<string, unknown>);
    }
    const choices = frame.choices as Array<{ delta?: { content?: unknown; tool_calls?: ToolCallFragment[] } }> | undefined;
    const delta = choices?.[0]?.delta;
    if (!delta) continue;
    if (typeof delta.content === "string" && delta.content) {
      text += delta.content;
      handlers.onText?.(text);
    }
    for (const fragment of delta.tool_calls ?? []) {
      const index = typeof fragment.index === "number" ? fragment.index : calls.size;
      const call = calls.get(index) ?? { id: "", name: "", arguments: "" };
      if (fragment.id) call.id = fragment.id;
      if (fragment.function?.name) call.name = fragment.function.name;
      if (fragment.function?.arguments) call.arguments += fragment.function.arguments;
      calls.set(index, call);
    }
  }
  const toolCalls = [...calls.entries()].sort(([a], [b]) => a - b).map(([, call]) => call);
  return { text, toolCalls, meta };
}
