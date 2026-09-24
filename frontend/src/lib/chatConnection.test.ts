/**
 * A reply cut off by a lost connection: told apart from other errors, worded
 * for the person holding the phone rather than for a server administrator.
 */
import { describe, expect, it } from "vitest";

import type { ChatMessage } from "./chatStorage";
import {
  CONNECTION_LOST_CONTENT,
  CONNECTION_LOST_MESSAGE,
  endsWithConnectionLost,
  isConnectionLostError,
} from "./chatConnection";

describe("isConnectionLostError", () => {
  it("recognises each browser's words for a lost connection", () => {
    for (const message of [
      "Failed to fetch",
      "network error",
      "NetworkError when attempting to fetch resource.",
      "Load failed",
      "The network connection was lost.",
    ]) {
      expect(isConnectionLostError(new TypeError(message)), message).toBe(true);
    }
  });

  it("leaves other errors and a Stop alone", () => {
    expect(isConnectionLostError(new Error("Model is overloaded"))).toBe(false);
    expect(isConnectionLostError(new DOMException("The user aborted a request.", "AbortError"))).toBe(false);
  });

  it("says what to do without mentioning Docker or a hard refresh", () => {
    expect(CONNECTION_LOST_MESSAGE).toBe("Connection lost. Check your connection and try again.");
    expect(CONNECTION_LOST_CONTENT).toBe(`Error: ${CONNECTION_LOST_MESSAGE}`);
    expect(CONNECTION_LOST_MESSAGE).not.toMatch(/docker|ctrl|refresh/i);
  });
});

describe("endsWithConnectionLost", () => {
  const user: ChatMessage = { role: "user", content: "Summarise this" };
  it("is true only when the last reply is the lost-connection error", () => {
    expect(endsWithConnectionLost([user, { role: "assistant", content: CONNECTION_LOST_CONTENT }])).toBe(true);
    expect(endsWithConnectionLost([user, { role: "assistant", content: "Here is the summary" }])).toBe(false);
    expect(endsWithConnectionLost([user, { role: "assistant", content: "Error: Model is overloaded" }])).toBe(false);
    expect(endsWithConnectionLost([{ role: "assistant", content: CONNECTION_LOST_CONTENT }, user])).toBe(false);
    expect(endsWithConnectionLost([])).toBe(false);
  });
});
