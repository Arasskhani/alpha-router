import type { ChatMessage } from "./chatStorage";

/**
 * A reply cut off because the device lost its connection: on a phone, going
 * offline or leaving the app mid-reply. The server treats the disconnect as
 * Stop and saves what it had, so the reply is fetched again once the device is
 * back online instead of being overwritten with this error.
 */
export const CONNECTION_LOST_MESSAGE = "Connection lost. Check your connection and try again.";
export const CONNECTION_LOST_CONTENT = `Error: ${CONNECTION_LOST_MESSAGE}`;

/** The browser's words for a request that never reached the server or lost it midway. */
export function isConnectionLostError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === "AbortError") return false;
  const message = err instanceof Error ? err.message : String(err ?? "");
  // Chrome "Failed to fetch" / "network error", Firefox "NetworkError when
  // attempting to fetch resource.", Safari "Load failed" / "The network
  // connection was lost."
  return /failed to fetch|network|load failed/i.test(message);
}

/** The thread's last message is a reply the lost connection cut off. */
export function endsWithConnectionLost(messages: readonly ChatMessage[]): boolean {
  const last = messages.at(-1);
  return last?.role === "assistant" && last.content === CONNECTION_LOST_CONTENT;
}
