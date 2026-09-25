/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { createMenus, handleMenuClick } from "./menus";
import { MAX_SELECTION_CHARS } from "./pageContext";

let chromeFake: ChromeFake;
const TAB = { id: 7, windowId: 3, url: "https://docs.example.com/guide?x=1", title: "The guide" } as chrome.tabs.Tab;

beforeEach(() => {
  chromeFake = installChromeFake();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function stored() {
  await vi.waitFor(async () => expect(await chrome.storage.session.get("alpharouter.pending-action")).not.toEqual({}));
  return (await chrome.storage.session.get("alpharouter.pending-action"))["alpharouter.pending-action"] as Record<string, unknown>;
}

describe("the right-click menu", () => {
  it("is made afresh, on web pages only: the page, and a selection", () => {
    createMenus();
    expect(chromeFake.contextMenus.removeAll).toHaveBeenCalledOnce();
    const made = chromeFake.contextMenus.create.mock.calls.map(([item]) => item);
    expect(made).toEqual([
      { id: "alpharouter-summarize", title: "Summarize this page", contexts: ["page"], documentUrlPatterns: ["http://*/*", "https://*/*"] },
      { id: "alpharouter-explain", title: "Explain “%s”", contexts: ["selection"], documentUrlPatterns: ["http://*/*", "https://*/*"] },
      {
        id: "alpharouter-translate",
        title: "Translate “%s” to Persian",
        contexts: ["selection"],
        documentUrlPatterns: ["http://*/*", "https://*/*"],
      },
      {
        id: "alpharouter-ask",
        title: "Ask Alpharouter about “%s”",
        contexts: ["selection"],
        documentUrlPatterns: ["http://*/*", "https://*/*"],
      },
    ]);
  });
});

describe("a click on it", () => {
  it("opens the side panel first, in the same turn as the click", () => {
    handleMenuClick({ menuItemId: "alpharouter-summarize", pageUrl: TAB.url, editable: false } as chrome.contextMenus.OnClickData, TAB);
    // Checked before anything awaited: Chrome allows opening the panel only then.
    expect(chromeFake.sidePanel.open).toHaveBeenCalledWith({ windowId: 3 });
  });

  it("leaves the work for the panel, and tells it", async () => {
    handleMenuClick({ menuItemId: "alpharouter-summarize", pageUrl: TAB.url, editable: false } as chrome.contextMenus.OnClickData, TAB);
    expect(await stored()).toMatchObject({
      kind: "summarize",
      tabId: 7,
      windowId: 3,
      pageUrl: "https://docs.example.com/guide?x=1",
      title: "The guide",
      selection: "",
      id: expect.any(String),
      createdAt: expect.any(Number),
    });
    await vi.waitFor(() => expect(chromeFake.runtime.sent).toEqual([{ type: "pending-action" }]));
  });

  it("keeps the selection for a selection action, capped one past what the model gets, to show it was cut", async () => {
    const selectionText = "x".repeat(MAX_SELECTION_CHARS + 20);
    handleMenuClick({ menuItemId: "alpharouter-translate", pageUrl: TAB.url, selectionText, editable: false } as chrome.contextMenus.OnClickData, TAB);
    const action = await stored();
    expect(action.kind).toBe("translate");
    expect(action.selection).toHaveLength(MAX_SELECTION_CHARS + 1);
  });

  it("takes a selection made inside a frame from the frame's page, without the tab's title", async () => {
    const frameUrl = "https://widget.other.example/embed?id=1";
    handleMenuClick(
      { menuItemId: "alpharouter-explain", pageUrl: TAB.url, frameUrl, selectionText: "Hi", editable: false } as chrome.contextMenus.OnClickData,
      TAB,
    );
    expect(await stored()).toMatchObject({ kind: "explain", pageUrl: frameUrl, title: "", selection: "Hi" });
  });

  it("keeps the page and its title for a selection in the page itself", async () => {
    handleMenuClick(
      { menuItemId: "alpharouter-explain", pageUrl: TAB.url, frameUrl: TAB.url, selectionText: "Hi", editable: false } as chrome.contextMenus.OnClickData,
      TAB,
    );
    expect(await stored()).toMatchObject({ pageUrl: TAB.url, title: "The guide" });
  });

  it("summarizes the tab's page even when the click was in a frame", async () => {
    handleMenuClick(
      { menuItemId: "alpharouter-summarize", pageUrl: TAB.url, frameUrl: "https://ads.example/x", editable: false } as chrome.contextMenus.OnClickData,
      TAB,
    );
    expect(await stored()).toMatchObject({ kind: "summarize", pageUrl: TAB.url, title: "The guide" });
  });

  it.each([
    ["another extension's item", { menuItemId: "other" }, TAB],
    ["no tab", { menuItemId: "alpharouter-summarize" }, undefined],
    ["a tab outside any window", { menuItemId: "alpharouter-summarize" }, { ...TAB, windowId: -1 }],
  ])("does nothing for %s", async (_name, info, tab) => {
    handleMenuClick({ pageUrl: TAB.url, editable: false, ...info } as chrome.contextMenus.OnClickData, tab as chrome.tabs.Tab | undefined);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(chromeFake.sidePanel.open).not.toHaveBeenCalled();
    expect(await chrome.storage.session.get("alpharouter.pending-action")).toEqual({});
  });
});
