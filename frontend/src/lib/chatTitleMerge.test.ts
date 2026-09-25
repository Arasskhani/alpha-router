import { afterEach, describe, expect, it, vi } from "vitest";
import * as apiMod from "../api";
import {
  fetchChatSessionTitle,
  mergeSessionAfterMessageLoad,
  type ChatSession,
} from "./chatStorage";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchChatSessionTitle", () => {
  const messages = [
    { role: "user", content: "Summarize this page" },
    { role: "assistant", content: "It says hello." },
  ];

  it("names the saved chat it titles, so the server knows whether it holds an answer about a page", async () => {
    const api = vi.spyOn(apiMod, "api").mockResolvedValue({ title: "Page summary" });
    await expect(fetchChatSessionTitle("model::3", messages, "chat-1")).resolves.toBe("Page summary");
    expect(JSON.parse(String(api.mock.calls[0][1]?.body))).toEqual({ model: "model::3", messages, chat_session_id: "chat-1" });
  });

  it("names no chat for one kept only in this browser", async () => {
    const api = vi.spyOn(apiMod, "api").mockResolvedValue({ title: "Page summary" });
    await fetchChatSessionTitle("model::3", messages);
    expect(JSON.parse(String(api.mock.calls[0][1]?.body))).toEqual({ model: "model::3", messages });
  });
});

function session(partial: Partial<ChatSession> & { id: string }): ChatSession {
  return {
    title: "New chat",
    model: "model-a",
    messages: [],
    createdAt: 1,
    updatedAt: 1,
    ...partial,
  };
}

describe("mergeSessionAfterMessageLoad", () => {
  it("keeps a local substantive title when the loaded row is still New chat", () => {
    const local = session({
      id: "s1",
      title: "Invoice analysis",
      titleGenerated: true,
    });
    const loaded = session({
      id: "s1",
      title: "New chat",
      messages: [{ role: "user", content: "Analyze invoices" }],
      messageCount: 1,
    });

    const merged = mergeSessionAfterMessageLoad(local, loaded);
    expect(merged.title).toBe("Invoice analysis");
    expect(merged.titleGenerated).toBe(true);
    expect(merged.messages).toEqual(loaded.messages);
  });

  it("accepts a better remote title when local is still the default", () => {
    const local = session({ id: "s1", title: "New chat" });
    const loaded = session({
      id: "s1",
      title: "Budget summary",
      titleGenerated: true,
      messages: [{ role: "user", content: "Summarize the budget" }],
    });

    const merged = mergeSessionAfterMessageLoad(local, loaded);
    expect(merged.title).toBe("Budget summary");
    expect(merged.titleGenerated).toBe(true);
  });

  it("honors a locked local title over a remote rename", () => {
    const local = session({
      id: "s1",
      title: "My pinned name",
      titleLocked: true,
    });
    const loaded = session({
      id: "s1",
      title: "Model generated",
      messages: [{ role: "user", content: "Hello" }],
    });

    const merged = mergeSessionAfterMessageLoad(local, loaded);
    expect(merged.title).toBe("My pinned name");
    expect(merged.titleLocked).toBe(true);
  });
});
