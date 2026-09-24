import type { ChatMessage } from "./chatStorage";

/**
 * A reply cut off because the device lost its connection: on a phone, going
 * offline or leaving the app mid-reply. The server treats the disconnect as
 * Stop and saves what it had, so the reply is fetched again (lib/replyRecovery.ts)
 * instead of being overwritten with this error.
 */
export const CONNECTION_LOST_MESSAGE = "Connection lost. Check your connection and try again.";
export const CONNECTION_LOST_CONTENT = `Error: ${CONNECTION_LOST_MESSAGE}`;

/**
 * The browser's own failure for a request that never reached the server or lost
 * it midway. fetch() and a stream read reject with a TypeError for that:
 * Chrome "Failed to fetch" / "network error", Firefox "NetworkError when
 * attempting to fetch resource.", Safari "Load failed" / "The network
 * connection was lost." An error the server or the model reported (a plain
 * Error, whatever its text says, such as "Network is unreachable" from a
 * provider) is not one.
 */
export function isConnectionLostError(err: unknown): boolean {
  if (!(err instanceof TypeError)) return false;
  return /failed to fetch|network|load failed/i.test(err.message);
}

/** The thread's last message is a reply the lost connection cut off. */
export function endsWithConnectionLost(messages: readonly ChatMessage[]): boolean {
  const last = messages.at(-1);
  return last?.role === "assistant" && last.content === CONNECTION_LOST_CONTENT;
}
