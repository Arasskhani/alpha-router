/**
 * A chat opened from the list holds only its latest page; the next turn must
 * go to the model with the whole chat, not with that page.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ api: vi.fn() }));

import { api } from "../api";
import { loadWholeSessionHistory, overlayLatestPage, sessionHasOlderMessages, setCachedSessionMessages, type ChatMessage, type ChatSession } from "./chatStorage";

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

function chat(messages: ChatMessage[], messageCount: number, id = "s-whole"): ChatSession {
  return { id, title: "Workout", model: "model::1", messages, createdAt: 1, updatedAt: 1, messageCount, revision: 3 };
}

/** The endpoint's paging: newest first below `before`, then oldest first within the page. */
function serveHistory(total: number) {
  mockedApi.mockImplementation(async (path: string) => {
    const url = new URL(path, "https://x.example");
    const limit = Number(url.searchParams.get("limit"));
    const before = url.searchParams.has("before") ? Number(url.searchParams.get("before")) : total + 1;
    const to = before - 1;
    const from = Math.max(1, to - limit + 1);
    return { messages: to >= 1 ? rows(from, to) : [], has_more: from > 1, revision: 3 };
  });
}

afterEach(() => {
  mockedApi.mockReset();
});

describe("loadWholeSessionHistory", () => {
  it("puts every older page in front of the page the chat was opened on", async () => {
    serveHistory(1200);
    const opened = chat(local(1151, 1200), 1200, "s-1200");
    const { session, added } = await loadWholeSessionHistory(opened);
    expect(added).toBe(1150);
    expect(session.messages).toHaveLength(1200);
    expect(session.messages[0].content).toBe("message 1");
    expect(session.messages.map((m) => m.sequence)).toEqual(Array.from({ length: 1200 }, (_, i) => i + 1));
    // In pages of 500, not 50: three requests for 1150 messages.
    expect(mockedApi).toHaveBeenCalledTimes(3);
    expect(sessionHasOlderMessages(session)).toBe(false);
  });

  it("keeps the loaded messages as they are, a reply still streaming included", async () => {
    serveHistory(60);
    const streaming: ChatMessage = { role: "assistant", content: "half a rep", streaming: true, clientMessageId: "live" };
    const opened = chat([...local(11, 60), streaming], 61, "s-live");
    const { session } = await loadWholeSessionHistory(opened);
    expect(session.messages).toHaveLength(61);
    expect(session.messages.at(-1)).toBe(streaming);
  });

  it("reads nothing for a chat already whole, a private one, or one with no server rows", async () => {
    serveHistory(40);
    expect((await loadWholeSessionHistory(chat(local(1, 40), 40, "s-40"))).added).toBe(0);
    expect((await loadWholeSessionHistory({ ...chat(local(11, 40), 40, "s-p"), privateMode: true })).added).toBe(0);
    expect((await loadWholeSessionHistory(chat([{ role: "user", content: "new" }], 5, "s-new"))).added).toBe(0);
    expect(mockedApi).not.toHaveBeenCalled();
  });

  it("trusts the cache over the chat's count once a page was read", async () => {
    serveHistory(60);
    const messages = local(11, 60);
    setCachedSessionMessages("s-cached", { revision: 3, messages, hasMoreOlder: true, oldestSequence: 11 });
    // The list's count lags (40), the cache knows there is more.
    expect(sessionHasOlderMessages(chat(messages, 40, "s-cached"))).toBe(true);
    setCachedSessionMessages("s-cached", { revision: 3, messages, hasMoreOlder: false, oldestSequence: 11 });
    expect(sessionHasOlderMessages(chat(messages, 200, "s-cached"))).toBe(false);
  });
});

describe("what fitting left out of an answer", () => {
  it("is read back with the answer's message", async () => {
    mockedApi.mockImplementation(async () => ({
      messages: [
        { role: "user", content: "message 1", sequence: 1, clientMessageId: "m1" },
        { role: "assistant", content: "message 2", sequence: 2, clientMessageId: "m2", contextFit: { dropped: 30, summarized: 20 } },
        { role: "assistant", content: "message 3", sequence: 3, clientMessageId: "m3", contextFit: { dropped: "x" } },
      ],
      has_more: false,
      revision: 3,
    }));
    const { session } = await loadWholeSessionHistory(chat(local(4, 5), 5, "s-fit"));
    expect(session.messages[1].contextFit).toEqual({ dropped: 30, summarized: 20 });
    expect(session.messages[2].contextFit).toBeUndefined();
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

  it("is the page when nothing here is older, and what is here when the page has no rows", () => {
    const page = local(1, 20);
    expect(overlayLatestPage(local(5, 20), page)).toBe(page);
    const here = local(1, 3);
    expect(overlayLatestPage(here, [])).toBe(here);
  });
});
