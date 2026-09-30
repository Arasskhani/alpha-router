/**
 * A chat opened from the list holds only its latest page. The server puts the
 * older messages in front of a turn (history_from_sequence); here, the page a
 * Stop or an image brings back is laid over the messages in hand without
 * losing any of them.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ api: vi.fn() }));

import { api } from "../api";
import { fetchChatSessionById, fetchSessionMessagesFromServer, overlayLatestPage, type ChatMessage } from "./chatStorage";

const mockedApi = vi.mocked(api);

/** Server rows 1..n, as the messages endpoint returns them. */
function rows(from: number, to: number): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  for (let s = from; s <= to; s += 1) {
    out.push({ role: s % 2 ? "user" : "assistant", content: `message ${s}`, sequence: s, clientMessageId: `m${s}` });
  }
  return out;
}

function local(from: number, to: number): ChatMessage[] {
  return rows(from, to).map((r) => ({ role: r.role as ChatMessage["role"], content: String(r.content), sequence: Number(r.sequence), clientMessageId: String(r.clientMessageId) }));
}

afterEach(() => {
  mockedApi.mockReset();
});

describe("what fitting left out of an answer, and the chats it read from", () => {
  it("are read back with the answer's message", async () => {
    mockedApi.mockImplementation(async () => ({
      messages: [
        { role: "user", content: "message 1", sequence: 1, clientMessageId: "m1" },
        {
          role: "assistant",
          content: "message 2",
          sequence: 2,
          clientMessageId: "m2",
          contextFit: { dropped: 30, summarized: 20 },
          recalledChats: [{ id: "s-9", title: "Workout" }],
        },
        { role: "assistant", content: "message 3", sequence: 3, clientMessageId: "m3", contextFit: { dropped: "x" } },
      ],
      has_more: false,
      revision: 3,
    }));
    const { messages } = await fetchSessionMessagesFromServer("s-fit", { limit: 50 });
    expect(messages[1].contextFit).toEqual({ dropped: 30, summarized: 20 });
    expect(messages[1].recalledChats).toEqual([{ id: "s-9", title: "Workout" }]);
    expect(messages[2].contextFit).toBeUndefined();
  });
});

describe("overlayLatestPage", () => {
  it("keeps the messages older than the server's page and takes the page for the rest", () => {
    const here = [...local(1, 58), { role: "assistant" as const, content: "half a rep", streaming: true }];
    const page = [...local(10, 58), { role: "assistant" as const, content: "Stopped.", sequence: 59, clientMessageId: "m59" }];
    const merged = overlayLatestPage(here, page);
    expect(merged).toHaveLength(59);
    expect(merged[0].content).toBe("message 1");
    expect(merged.at(-1)?.content).toBe("Stopped.");
  });

  it("keeps a turn sent while the page was on its way, but not a copy of what the page has", () => {
    const stopped = { role: "assistant" as const, content: "Stopped.", sequence: 59, clientMessageId: "a59" };
    const here = [
      ...local(1, 58),
      { role: "assistant" as const, content: "half a rep", clientMessageId: "a59", streaming: true },
      { role: "user" as const, content: "And now?", clientMessageId: "u60" },
      { role: "assistant" as const, content: "", clientMessageId: "a61", streaming: true },
    ];
    const merged = overlayLatestPage(here, [...local(10, 58), stopped]);
    expect(merged.map((m) => m.content).slice(-3)).toEqual(["Stopped.", "And now?", ""]);
    expect(merged.filter((m) => m.clientMessageId === "a59")).toEqual([stopped]);
    expect(merged).toHaveLength(61);
  });

  it("is the page when nothing here is older, and what is here when the page has no rows", () => {
    const page = local(1, 20);
    expect(overlayLatestPage(local(5, 20), page)).toBe(page);
    const here = local(1, 3);
    expect(overlayLatestPage(here, [])).toBe(here);
  });
});

describe("a chat an answer read from, when the list has not loaded it", () => {
  it("is read by id", async () => {
    mockedApi.mockResolvedValueOnce({ id: "s-old", title: "Workout", model: "model::1", messageCount: 12, revision: 4 });
    const found = await fetchChatSessionById("s-old");
    expect(mockedApi).toHaveBeenCalledWith("/api/user/chat-sessions/s-old");
    expect(found).toMatchObject({ id: "s-old", title: "Workout", messageCount: 12, messages: [] });
  });

  it("is nothing when it cannot be read", async () => {
    mockedApi.mockRejectedValueOnce(new Error("Session not found"));
    expect(await fetchChatSessionById("s-gone")).toBeNull();
  });
});
