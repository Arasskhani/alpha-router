import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ api: vi.fn() }));

import { api } from "../api";
import {
  fetchAllSessionMessagesFromServer,
  mergeRemoteChatSessions,
  messagesMissingOnServer,
  pickMergedMessages,
  type ChatMessage,
  type ChatSession,
} from "./chatStorage";

const mockedApi = vi.mocked(api);

function msg(partial: Partial<ChatMessage> & { content: string }): ChatMessage {
  return { role: "user", ...partial };
}

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

afterEach(() => {
  mockedApi.mockReset();
});

describe("messagesMissingOnServer", () => {
  it("diffs by clientMessageId instead of position", () => {
    const server = [
      msg({ content: "a", clientMessageId: "c1" }),
      msg({ content: "from other device", clientMessageId: "c9", role: "assistant" }),
    ];
    const local = [
      msg({ content: "a", clientMessageId: "c1" }),
      msg({ content: "b", clientMessageId: "c2" }),
      msg({ content: "c", clientMessageId: "c3", role: "assistant" }),
    ];
    // Positional diff would have appended only "c" (local.length - server.length = 1).
    expect(messagesMissingOnServer(local, server).map((m) => m.clientMessageId)).toEqual(["c2", "c3"]);
  });

  it("returns nothing when the server already has every id", () => {
    const rows = [msg({ content: "a", clientMessageId: "c1" }), msg({ content: "b", clientMessageId: "c2" })];
    expect(messagesMissingOnServer(rows, [...rows].reverse())).toEqual([]);
  });

  it("matches legacy rows without clientMessageId by position", () => {
    const server = [msg({ content: "old-1" }), msg({ content: "old-2" })];
    const local = [
      msg({ content: "old-1" }),
      msg({ content: "old-2" }),
      msg({ content: "old-3" }),
      msg({ content: "new", clientMessageId: "n1" }),
    ];
    expect(messagesMissingOnServer(local, server).map((m) => m.content)).toEqual(["old-3", "new"]);
  });
});

describe("pickMergedMessages", () => {
  const older = [msg({ content: "a" }), msg({ content: "b" }), msg({ content: "c" })];
  const newer = [msg({ content: "a" }), msg({ content: "c" })];

  it("lets a newer, shorter remote list win (a deletion on another device)", () => {
    const local = session({ id: "s", messages: older, updatedAt: 100 });
    const remote = session({ id: "s", messages: newer, updatedAt: 200 });
    expect(pickMergedMessages(local, remote)).toBe(newer);
  });

  it("keeps the newer local list", () => {
    const local = session({ id: "s", messages: newer, updatedAt: 300 });
    const remote = session({ id: "s", messages: older, updatedAt: 200 });
    expect(pickMergedMessages(local, remote)).toBe(newer);
  });

  it("never lets an unloaded remote (no messages) erase local messages", () => {
    const local = session({ id: "s", messages: older, updatedAt: 100 });
    const remote = session({ id: "s", messages: [], updatedAt: 999 });
    expect(pickMergedMessages(local, remote)).toBe(older);
  });

  it("falls back to the longer list only on a timestamp tie", () => {
    const local = session({ id: "s", messages: newer, updatedAt: 100 });
    const remote = session({ id: "s", messages: older, updatedAt: 100 });
    expect(pickMergedMessages(local, remote)).toBe(older);
  });
});

describe("mergeRemoteChatSessions", () => {
  it("takes remote scalar fields when the remote copy is newer", () => {
    const local = [session({ id: "s", folderId: "f-old", pinned: false, updatedAt: 100 })];
    const remote = [session({ id: "s", folderId: "f-new", pinned: true, updatedAt: 200, revision: 7 })];
    const [merged] = mergeRemoteChatSessions(local, remote);
    expect(merged.folderId).toBe("f-new");
    expect(merged.pinned).toBe(true);
    expect(merged.revision).toBe(7);
    expect(merged.updatedAt).toBe(200);
  });

  it("keeps local scalar fields when the local copy is newer", () => {
    const local = [session({ id: "s", folderId: "f-local", updatedAt: 300 })];
    const remote = [session({ id: "s", folderId: "f-remote", updatedAt: 200 })];
    const [merged] = mergeRemoteChatSessions(local, remote);
    expect(merged.folderId).toBe("f-local");
  });

  it("always takes the server's Agent selection", () => {
    const local = [session({ id: "s", currentAgentId: "local-agent", updatedAt: 300 })];
    const remote = [session({ id: "s", currentAgentId: "server-agent", updatedAt: 200 })];
    expect(mergeRemoteChatSessions(local, remote)[0].currentAgentId).toBe("server-agent");
  });

  it("keeps local messages for protected (streaming) sessions", () => {
    const streaming = [msg({ content: "partial", role: "assistant", streaming: true })];
    const local = [session({ id: "s", messages: streaming, updatedAt: 100 })];
    const remote = [session({ id: "s", messages: [msg({ content: "done", role: "assistant" })], updatedAt: 500 })];
    expect(mergeRemoteChatSessions(local, remote, ["s"])[0].messages).toBe(streaming);
  });
});

describe("fetchAllSessionMessagesFromServer", () => {
  it("walks `before` pages and returns the whole history oldest-first", async () => {
    mockedApi.mockImplementation(async (path: string) => {
      const url = new URL(`http://x${path}`);
      const before = url.searchParams.get("before");
      if (before === null) {
        return {
          messages: [
            { role: "user", content: "3", sequence: 3 },
            { role: "assistant", content: "4", sequence: 4 },
          ],
          has_more: true,
          revision: 5,
        };
      }
      expect(before).toBe("3");
      return {
        messages: [
          { role: "user", content: "1", sequence: 1 },
          { role: "assistant", content: "2", sequence: 2 },
        ],
        has_more: false,
      };
    });
    const result = await fetchAllSessionMessagesFromServer("s1", { pageSize: 2 });
    expect(result.messages.map((m) => m.content)).toEqual(["1", "2", "3", "4"]);
    expect(result.revision).toBe(5);
    expect(result.truncated).toBe(false);
    expect(mockedApi).toHaveBeenCalledTimes(2);
  });

  it("stops after one page when the server reports no more", async () => {
    mockedApi.mockResolvedValue({
      messages: [{ role: "user", content: "only", sequence: 1 }],
      has_more: false,
    });
    const result = await fetchAllSessionMessagesFromServer("s1");
    expect(result.messages).toHaveLength(1);
    expect(mockedApi).toHaveBeenCalledTimes(1);
  });
});
