/**
 * One step's model call for the browser agent: a /api/chat/completions
 * stream, read to its end, within time limits, tried again once when it
 * fails in a way a second try can mend.
 *
 * A model can take its time - a reasoning model with three screenshots may
 * think for a minute - but a call that sends nothing for `idleMs` (not even
 * a keep-alive), or runs past `totalMs`, is not coming back: it is dropped.
 * Dropped, cut short, answered with a server error or an error frame, or
 * lost to the network, it is tried once more; anything else (a refusal, a
 * Stop) is final. The caller shows the wait (onText) while it lasts.
 */

import { ApiError } from "../lib/api";
import { ChatStreamError, readChatStream, type StreamResult } from "../lib/chatStream";
import { DisconnectedError } from "../lib/tokens";

/** Without a byte from the server for this long, a step is given up. */
export const MODEL_IDLE_MS = 90_000;
/** However the server keeps it alive, a step never takes longer than this. */
export const MODEL_TOTAL_MS = 240_000;
/** A step that failed in a way a second try can mend is tried this many more times. */
export const MODEL_RETRIES = 1;

export class ModelTimeout extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ModelTimeout";
  }
}

export type ModelStepCall = {
  /** Send the step; `signal` ends it (a Stop, or a limit). */
  request: (signal: AbortSignal) => Promise<Response>;
  /** The model's words so far, as they come. */
  onText?: (full: string) => void;
  /** A try failed and another is on its way: why. */
  onRetry?: (why: string) => void;
  idleMs?: number;
  totalMs?: number;
  retries?: number;
};

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

/** Whether a second try may mend what went wrong: a limit, a cut or failed stream, a server error, the network. */
function worthRetrying(err: unknown): boolean {
  if (err instanceof ModelTimeout || err instanceof ChatStreamError) return true;
  if (err instanceof ApiError) return err.status >= 500;
  if (err instanceof DisconnectedError) return false;
  // fetch() rejects with a TypeError when the network fails.
  return err instanceof TypeError;
}

async function once(call: ModelStepCall, stepSignal: AbortSignal): Promise<StreamResult> {
  const idleMs = call.idleMs ?? MODEL_IDLE_MS;
  const totalMs = call.totalMs ?? MODEL_TOTAL_MS;
  const attempt = new AbortController();
  let limit: ModelTimeout | null = null;
  const drop = (why: string) => {
    limit = new ModelTimeout(why);
    attempt.abort();
  };
  const onStop = () => attempt.abort();
  if (stepSignal.aborted) attempt.abort();
  else stepSignal.addEventListener("abort", onStop, { once: true });
  let idle = setTimeout(() => drop(`The model sent nothing for ${Math.round(idleMs / 1000)} s.`), idleMs);
  const total = setTimeout(() => drop(`The model did not finish within ${Math.round(totalMs / 1000)} s.`), totalMs);
  const alive = () => {
    clearTimeout(idle);
    idle = setTimeout(() => drop(`The model sent nothing for ${Math.round(idleMs / 1000)} s.`), idleMs);
  };
  try {
    const response = await call.request(attempt.signal);
    if (!response.ok) throw await ApiError.from(response);
    return await readChatStream(response, { onText: call.onText, onActivity: alive });
  } catch (err) {
    if (stepSignal.aborted) throw new DOMException("The run was stopped.", "AbortError");
    if (limit && (isAbort(err) || err instanceof TypeError || err instanceof ChatStreamError)) throw limit;
    throw err;
  } finally {
    clearTimeout(idle);
    clearTimeout(total);
    stepSignal.removeEventListener("abort", onStop);
  }
}

/** The step's reply, within the limits, with one more try when that can help. */
export async function modelStep(call: ModelStepCall, stepSignal: AbortSignal): Promise<StreamResult> {
  const retries = call.retries ?? MODEL_RETRIES;
  for (let tried = 0; ; tried += 1) {
    try {
      return await once(call, stepSignal);
    } catch (err) {
      if (isAbort(err) || stepSignal.aborted) throw err;
      if (tried >= retries || !worthRetrying(err)) throw err;
      call.onRetry?.(err instanceof Error && err.message ? err.message : "The model's answer did not come through.");
    }
  }
}
