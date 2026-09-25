/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { broadcast, fromOwnPages, fromTabScript, isExtensionMessage } from "./messages";

const ID = "abcdefghijklmnopabcdefghijklmnop";
const sendMessage = vi.fn();

beforeEach(() => {
  sendMessage.mockReset();
  vi.stubGlobal("chrome", { runtime: { id: ID, getURL: (p: string) => `chrome-extension://${ID}/${p}`, sendMessage } });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("messages between the extension's pages", () => {
  it.each([{ type: "auth-changed" }, { type: "pending-action" }, { type: "agent-stop", run: "run-12_a" }])("accepts %o", (message) => {
    expect(isExtensionMessage(message)).toBe(true);
  });

  it.each([null, "auth-changed", {}, { type: "unknown" }, { type: 7 }, { type: "agent-stop" }, { type: "agent-stop", run: "a b" }])(
    "refuses %o",
    (message) => {
      expect(isExtensionMessage(message)).toBe(false);
    },
  );

  it("take a Stop from the agent's overlay only from our content script in that tab", () => {
    const page = { id: ID, url: "https://shop.example.com/cart", tab: { id: 5 } as chrome.tabs.Tab };
    expect(fromTabScript(page, 5)).toBe(true);
    expect(fromTabScript(page, 6)).toBe(false);
    expect(fromTabScript({ ...page, id: "someotherextension" }, 5)).toBe(false);
    // One of our own pages in a tab is not the overlay.
    expect(fromTabScript({ id: ID, url: `chrome-extension://${ID}/connected.html`, tab: { id: 5 } as chrome.tabs.Tab }, 5)).toBe(false);
  });

  it("are accepted only from this extension's own pages", () => {
    expect(fromOwnPages({ id: ID, url: `chrome-extension://${ID}/sidepanel.html` })).toBe(true);
    // connected.html runs in a tab and is still ours.
    expect(fromOwnPages({ id: ID, url: `chrome-extension://${ID}/connected.html`, tab: { id: 3 } as chrome.tabs.Tab })).toBe(true);
    // A content script of ours carries the web page's URL.
    expect(fromOwnPages({ id: ID, url: "https://example.com/", tab: { id: 3 } as chrome.tabs.Tab })).toBe(false);
    expect(fromOwnPages({ id: "someotherextension", url: `chrome-extension://someotherextension/x.html` })).toBe(false);
    expect(fromOwnPages({ id: ID })).toBe(false);
  });

  it("go out without failing when nothing is listening", async () => {
    sendMessage.mockRejectedValueOnce(new Error("Could not establish connection. Receiving end does not exist."));
    await expect(broadcast({ type: "auth-changed" })).resolves.toBeUndefined();
    expect(sendMessage).toHaveBeenCalledWith({ type: "auth-changed" });
  });
});
