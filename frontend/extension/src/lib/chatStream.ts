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
  /**
   * The model's reasoning as the provider hands it back (OpenRouter's
   * `reasoning_details`: summaries, encrypted blocks, thought signatures):
   * sent back with the tool calls it came with, as Gemini and others require
   * to go on from them. Never shown.
   */
  reasoningDetails?: unknown[];
};

export type StreamHandlers = {
  onText?: (full: string) => void;
  onMeta?: (meta: Record<string, unknown>) => void;
  /** Whenever bytes arrive - a frame, or a keep-alive comment: the stream is alive. */
  onActivity?: () => void;
};

export class ChatStreamError extends Error {
  /** Whether asking again may get a whole answer: a cut or failed stream may; one cut at its length limit will not. */
  readonly retryable: boolean;

  constructor(message: string, options: { retryable?: boolean } = {}) {
    super(message);
    this.name = "ChatStreamError";
    this.retryable = options.retryable ?? true;
  }
}

type ToolCallFragment = {
  index?: number;
  id?: string;
  function?: { name?: string; arguments?: string };
};

type Part = { content?: unknown; tool_calls?: ToolCallFragment[]; reasoning_details?: unknown };

type Choice = {
  delta?: Part;
  /** A provider that sends the whole answer at once, not in pieces. */
  message?: Part;
  finish_reason?: unknown;
};

/** The reasoning kept from one answer, in characters of JSON: past it, readable text goes first, signed blocks never. */
const MAX_REASONING_CHARS = 256_000;

type ReasoningEntry = Record<string, unknown>;

/** The fields of a reasoning entry that stream in pieces, joined; the rest (its type, id, signature, data) is the last given. */
const PIECEWISE = new Set(["text", "summary"]);

/**
 * Put a streamed reasoning fragment with the entry it belongs to: by its
 * `index` when it has one (OpenRouter sends an entry in many deltas),
 * else as an entry of its own.
 */
function mergeReasoning(into: ReasoningEntry[], fragment: ReasoningEntry): void {
  const index = typeof fragment.index === "number" ? fragment.index : undefined;
  const entry = index === undefined ? undefined : into.find((e) => e.index === index);
  if (!entry) {
    into.push({ ...fragment });
    return;
  }
  for (const [key, value] of Object.entries(fragment)) {
    if (PIECEWISE.has(key) && typeof value === "string" && typeof entry[key] === "string") entry[key] = `${entry[key] as string}${value}`;
    else if (value !== undefined && value !== null && value !== "") entry[key] = value;
  }
}

/** Whether an entry is signed or encrypted - what a provider checks - rather than reasoning to read. */
export function signedReasoning(entry: unknown): boolean {
  if (!entry || typeof entry !== "object") return false;
  const e = entry as ReasoningEntry;
  return e.type === "reasoning.encrypted" || Boolean(e.signature) || Boolean(e.data);
}

/** The answer's reasoning within its limit: the readable entries go first, from the oldest; signed ones stay. */
function boundedReasoning(entries: ReasoningEntry[]): ReasoningEntry[] {
  const kept = [...entries];
  const total = () => JSON.stringify(kept).length;
  for (let i = 0; i < kept.length && total() > MAX_REASONING_CHARS; ) {
    if (signedReasoning(kept[i])) i += 1;
    else kept.splice(i, 1);
  }
  return kept;
}

export type StreamOptions = {
  /**
   * The answer must be whole: the stream ends with [DONE] or says why it
   * finished. A stream that just stops - a proxy cutting it, the server going
   * away - is then an error, not an answer; so is one cut at its length limit
   * in the middle of a tool call. For the agent, which acts on what it gets.
   */
  strict?: boolean;
};

function parses(json: string): boolean {
  try {
    JSON.parse(json || "{}");
    return true;
  } catch {
    return false;
  }
}

function errorText(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object" && typeof (error as { message?: unknown }).message === "string") {
    return (error as { message: string }).message;
  }
  return "The model could not answer.";
}

export async function readChatStream(response: Response, handlers: StreamHandlers = {}, options: StreamOptions = {}): Promise<StreamResult> {
  if (!response.body) throw new ChatStreamError("The server sent no reply.");
  let text = "";
  const meta: Record<string, unknown> = {};
  /** The calls in the order they began; each fragment finds its call by index, and a new id at a used index is a new call. */
  const calls: ToolCall[] = [];
  const byIndex = new Map<number, ToolCall>();
  let done = false;
  let finish: string | null = null;
  const reasoning: ReasoningEntry[] = [];
  const take = (fragment: ToolCallFragment) => {
    let call: ToolCall | undefined;
    if (typeof fragment.index === "number") {
      call = byIndex.get(fragment.index);
      // Two calls under one index (some providers number them all 0): a new id starts a new one.
      if (call && fragment.id && call.id && fragment.id !== call.id) call = undefined;
    } else {
      // No index: a piece of the last call, unless it names another.
      const last = calls[calls.length - 1];
      call = last && (!fragment.id || !last.id || fragment.id === last.id) ? last : undefined;
    }
    if (!call) {
      call = { id: "", name: "", arguments: "" };
      calls.push(call);
      if (typeof fragment.index === "number") byIndex.set(fragment.index, call);
    }
    if (fragment.id) call.id = fragment.id;
    if (fragment.function?.name) call.name = fragment.function.name;
    if (fragment.function?.arguments) call.arguments += fragment.function.arguments;
  };
  const raw = response.body.getReader();
  // The reader as the SSE parser sees it, telling the caller each time bytes come - keep-alive comments too.
  const reader = {
    read: async () => {
      const chunk = await raw.read();
      handlers.onActivity?.();
      return chunk;
    },
    cancel: (reason?: unknown) => raw.cancel(reason),
    releaseLock: () => raw.releaseLock(),
    closed: raw.closed,
  } as ReadableStreamDefaultReader<Uint8Array>;
  for await (const payload of readSseEvents(reader)) {
    if (payload === "[DONE]") {
      done = true;
      continue;
    }
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
    const choice = (frame.choices as Choice[] | undefined)?.[0];
    if (!choice) continue;
    if (typeof choice.finish_reason === "string" && choice.finish_reason) finish = choice.finish_reason;
    const part = choice.delta ?? choice.message;
    if (!part) continue;
    if (typeof part.content === "string" && part.content) {
      text += part.content;
      handlers.onText?.(text);
    }
    for (const fragment of part.tool_calls ?? []) take(fragment);
    if (Array.isArray(part.reasoning_details)) {
      for (const detail of part.reasoning_details) if (detail && typeof detail === "object") mergeReasoning(reasoning, detail as ReasoningEntry);
    }
  }
  if (options.strict) {
    if (!done && !finish) throw new ChatStreamError("The model's answer was cut short.");
    if (finish === "length" && calls.some((call) => !parses(call.arguments))) {
      throw new ChatStreamError("The model's answer was cut at its length limit, in the middle of an action.", { retryable: false });
    }
  }
  return { text, toolCalls: calls, meta, ...(reasoning.length ? { reasoningDetails: boundedReasoning(reasoning) } : {}) };
}
