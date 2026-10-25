/**
 * The Exchange mailbox in stored chats: a chat's mail switch comes back with
 * the chat, per chat.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ api: vi.fn() }));

import { api } from "../api";
import { fetchChatSessionById } from "./chatStorage";
import { copyFreshChatTools } from "./chatTools";
import { mailOnForChat } from "./mailChatSwitch";

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
