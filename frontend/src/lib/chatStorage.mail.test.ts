/**
 * The Exchange mailbox in stored chats: a chat's mail switch comes back with
 * the chat, per chat, and an answer's draft cards and its mail mark with its
 * message.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ api: vi.fn() }));

import { api } from "../api";
import { fetchChatSessionById, fetchSessionMessagesFromServer } from "./chatStorage";
import { copyFreshChatTools } from "./chatTools";
import { mailOnForChat } from "./mailChatSwitch";
import { answerImages } from "./sharedPages";

const mockedApi = vi.mocked(api);

afterEach(() => {
  mockedApi.mockReset();
});

describe("a chat's mail switch", () => {
  it("comes back with the chat from the server, per chat", async () => {
    mockedApi.mockImplementation(async (path: string) =>
      path.endsWith("/off")
        ? { id: "off", title: "Budget", model: "m", tools: { ...copyFreshChatTools(), mailOff: true }, toolsTouched: true }
        : { id: "on", title: "Lunch", model: "m", tools: copyFreshChatTools(), toolsTouched: true },
    );
    const off = await fetchChatSessionById("off");
    const on = await fetchChatSessionById("on");
    expect(off?.tools?.mailOff).toBe(true);
    expect(mailOnForChat(off!.tools!)).toBe(false);
    expect(mailOnForChat(on!.tools!)).toBe(true);
  });
});

describe("an answer's draft cards", () => {
  it("are read back with the answer's message, malformed ones dropped", async () => {
    const draft = {
      id: 12,
      mailbox: "s.karimi@corp.example",
      kind: "reply",
      subject: "Re: Budget 1405",
      to: [{ name: "Ali Rezaei", email: "a.rezaei@corp.example" }],
      cc: [],
      preview: "Hello Ali, the figures are attached.",
    };
    mockedApi.mockImplementation(async () => ({
      messages: [
        { role: "user", content: "Draft a reply to Ali", sequence: 1, clientMessageId: "m1" },
        { role: "assistant", content: "I saved a draft.", sequence: 2, clientMessageId: "m2", mailDrafts: [draft, { id: -1 }] },
        { role: "assistant", content: "No drafts here.", sequence: 3, clientMessageId: "m3", mailDrafts: "nope" },
      ],
      has_more: false,
      revision: 1,
    }));
    const { messages } = await fetchSessionMessagesFromServer("s-mail", { limit: 50 });
    expect(messages[1].mailDrafts).toEqual([draft]);
    expect(messages[0].mailDrafts).toBeUndefined();
    expect(messages[2].mailDrafts).toBeUndefined();
  });
});

describe("an answer's mail mark", () => {
  it("is read back with the answer's message, so its images stay links after a reload", async () => {
    mockedApi.mockImplementation(async () => ({
      messages: [
        { role: "user", content: "Summarise my unread mail", sequence: 1, clientMessageId: "m1" },
        { role: "assistant", content: "Three emails…", sequence: 2, clientMessageId: "m2", mailContext: { read: true } },
        { role: "assistant", content: "Plain answer", sequence: 3, clientMessageId: "m3" },
      ],
      has_more: false,
      revision: 1,
    }));
    const { messages } = await fetchSessionMessagesFromServer("s-mail-read", { limit: 50 });
    expect(messages[1].mailContext).toEqual({ read: true });
    expect(answerImages(messages[1])).toBe("link");
    expect(messages[2].mailContext).toBeUndefined();
    expect(answerImages(messages[2])).toBe("load");
  });
});
