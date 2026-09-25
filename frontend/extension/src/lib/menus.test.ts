/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { MAX_MENU_SELECTION_CHARS, createMenus, handleMenuClick } from "./menus";

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

  it("keeps the selection for a selection action, capped", async () => {
    const selectionText = "x".repeat(MAX_MENU_SELECTION_CHARS + 20);
    handleMenuClick({ menuItemId: "alpharouter-translate", pageUrl: TAB.url, selectionText, editable: false } as chrome.contextMenus.OnClickData, TAB);
    const action = await stored();
    expect(action.kind).toBe("translate");
    expect(action.selection).toHaveLength(MAX_MENU_SELECTION_CHARS);
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
