import { describe, expect, it } from "vitest";
import { stableMessageKeys, type ChatMessage } from "./chatStorage";

const m = (over: Partial<ChatMessage>): ChatMessage => ({ role: "user", content: "", ...over });

describe("stableMessageKeys", () => {
  it("keeps a row's key when a row above it is removed", () => {
    const list = [m({ clientMessageId: "c1" }), m({ role: "assistant", clientMessageId: "c1" }), m({ clientMessageId: "c2" })];
    const before = stableMessageKeys(list, "s");
    const after = stableMessageKeys(list.slice(1), "s");
    expect(after).toEqual(before.slice(1));
  });

  it("never returns duplicate keys", () => {
    const list = [
      m({ clientMessageId: "c1" }),
      m({ clientMessageId: "c1" }), // pathological duplicate
      m({ role: "assistant", clientMessageId: "c1", modelId: "a" }),
      m({ role: "assistant", clientMessageId: "c1", modelId: "b" }),
      m({}),
      m({}),
    ];
    const keys = stableMessageKeys(list, "s");
    expect(new Set(keys).size).toBe(keys.length);
  });
});
