import { CONNECTION_LOST_CONTENT, endsWithConnectionLost } from "./chatConnection";
import type { ChatMessage } from "./chatStorage";

/** How often, and for how long, a cut-off reply is looked for on the server. */
export const RECOVERY_RETRY_MS = 5_000;
export const RECOVERY_MAX_TRIES = 120;
/**
 * A reply the server still marks as streaming this long after it was cut off is
 * taken as abandoned (the server restarted mid-reply). Long enough for a slow
 * model that is still writing because the server never saw the disconnect.
 */
export const RECOVERY_STUCK_MS = 5 * 60_000;

export type ReplyRecoveryDeps = {
  activeSessionId: () => string | null;
  messagesOf: (sessionId: string) => ChatMessage[];
  /** Private chats keep nothing on the server, and a read-only view writes nothing. */
  skip: (sessionId: string) => boolean;
  /** A turn is running in this chat: it owns the thread for now. */
  busy: (sessionId: string) => boolean;
  fetchRemote: (sessionId: string) => Promise<ChatMessage[] | null>;
  /** Replace the thread's last message (the lost-connection error) with the server's reply. */
  replaceLast: (sessionId: string, message: ChatMessage) => void;
  /** Close a reply the server abandoned mid-stream, so it stops counting as running. */
  finalizeAbandoned: (sessionId: string, message: ChatMessage) => void;
  now?: () => number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (timer: unknown) => void;
};

/**
 * Brings back a reply cut off by a lost connection. The server treats a client
 * that disconnects as Stop and saves what it had; the chat meanwhile shows the
 * lost-connection error in that reply's place. Once nudged (the error was just
 * shown, the device is back online, the app is back in view), it asks the
 * server for that reply every few seconds, for up to ten minutes, and puts the
 * saved one in place of the error. A reply the server is still writing is
 * waited for; one it still marks as streaming after five minutes (the server
 * restarted mid-reply) is closed with the error appended, so it stops counting
 * as running.
 */
export function createReplyRecovery(deps: ReplyRecoveryDeps) {
  const now = deps.now ?? Date.now;
  const setTimer = deps.setTimer ?? ((fn: () => void, ms: number) => window.setTimeout(fn, ms));
  const clearTimer = deps.clearTimer ?? ((timer: unknown) => window.clearTimeout(timer as number));
  let run: {
    sessionId: string;
    errorId: string;
    tries: number;
    startedAt: number;
    timer: unknown;
    /** An attempt is waiting for the server. */
    busy: boolean;
  } | null = null;

  const stop = () => {
    if (run?.timer !== undefined && run.timer !== null) clearTimer(run.timer);
    run = null;
  };

  /** The thread still ends with the same lost-connection error this run is for. */
  const stillCutOff = (sessionId: string, errorId: string) => {
    const local = deps.messagesOf(sessionId);
    return endsWithConnectionLost(local) && (local.at(-1)?.clientMessageId ?? "") === errorId;
  };

  const retry = () => {
    if (!run) return;
    run.tries += 1;
    if (run.tries >= RECOVERY_MAX_TRIES) {
      stop();
      return;
    }
    run.timer = setTimer(() => void attempt(), RECOVERY_RETRY_MS);
  };

  async function attempt(): Promise<void> {
    if (!run) return;
    const current = run;
    const { sessionId, errorId, startedAt } = current;
    current.timer = null;
    if (deps.activeSessionId() !== sessionId || deps.skip(sessionId) || !stillCutOff(sessionId, errorId)) {
      stop();
      return;
    }
    if (deps.busy(sessionId)) {
      retry();
      return;
    }
    let remote: ChatMessage[] | null = null;
    current.busy = true;
    try {
      remote = await deps.fetchRemote(sessionId);
    } catch {
      remote = null;
    } finally {
      current.busy = false;
    }
    if (run !== current) return;
    if (deps.activeSessionId() !== sessionId || deps.skip(sessionId) || !stillCutOff(sessionId, errorId)) {
      stop();
      return;
    }
    if (deps.busy(sessionId)) {
      retry();
      return;
    }
    const saved = remote?.find((m) => m.role === "assistant" && m.clientMessageId === errorId);
    if (!saved) {
      retry();
      return;
    }
    const finished = saved.streaming !== true && saved.receivedAt != null;
    if (finished) {
      deps.replaceLast(sessionId, saved);
      stop();
      return;
    }
    if (now() - startedAt >= RECOVERY_STUCK_MS) {
      const partial = (saved.content || "").trim();
      const closed: ChatMessage = {
        ...saved,
        content: partial ? `${saved.content}\n\n${CONNECTION_LOST_CONTENT}` : CONNECTION_LOST_CONTENT,
        streaming: false,
        receivedAt: saved.receivedAt ?? now(),
      };
      deps.finalizeAbandoned(sessionId, closed);
      deps.replaceLast(sessionId, closed);
      stop();
      return;
    }
    retry();
  }

  return {
    /**
     * Look for the open chat's cut-off reply (after `delayMs`, or now), and keep
     * looking for a while. Right after the error, the turn that failed is still
     * winding down, so the first look waits.
     */
    nudge(delayMs = 0): void {
      const sessionId = deps.activeSessionId();
      if (!sessionId || deps.skip(sessionId)) return;
      const last = deps.messagesOf(sessionId).at(-1);
      if (!endsWithConnectionLost(deps.messagesOf(sessionId)) || !last?.clientMessageId) return;
      if (run && run.sessionId === sessionId && run.errorId === last.clientMessageId) {
        // Already looking: a fresh budget, and a look now unless one is under way.
        run.tries = 0;
        if (run.busy) return;
        if (run.timer !== null && run.timer !== undefined) clearTimer(run.timer);
        run.timer = delayMs > 0 ? setTimer(() => void attempt(), delayMs) : null;
        if (delayMs <= 0) void attempt();
        return;
      }
      stop();
      run = { sessionId, errorId: last.clientMessageId, tries: 0, startedAt: now(), timer: null, busy: false };
      if (delayMs > 0) run.timer = setTimer(() => void attempt(), delayMs);
      else void attempt();
    },
    stop,
  };
}
