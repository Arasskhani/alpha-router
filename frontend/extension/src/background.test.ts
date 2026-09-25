/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installChromeFake, type ChromeFake } from "./test/chromeFake";

let chromeFake: ChromeFake;

beforeEach(async () => {
  chromeFake = installChromeFake();
  vi.resetModules();
  await import("./background");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the service worker", () => {
  it("opens the panel from the toolbar button (and so the shortcut) on every start", () => {
    expect(chromeFake.sidePanel.setPanelBehavior).toHaveBeenCalledWith({ openPanelOnActionClick: true });
  });

  it("makes the right-click menu when the extension is installed or updated, and only then", () => {
    expect(chromeFake.contextMenus.create).not.toHaveBeenCalled();
    chromeFake.runtime.onInstalled.emit();
    expect(chromeFake.contextMenus.create).toHaveBeenCalledTimes(4);
  });

  it("answers a menu click from the moment it starts", () => {
    const tab = { id: 7, windowId: 3, url: "https://example.com/", title: "Example" } as chrome.tabs.Tab;
    chromeFake.contextMenus.onClicked.emit({ menuItemId: "alpharouter-summarize", pageUrl: tab.url } as never, tab as never);
    expect(chromeFake.sidePanel.open).toHaveBeenCalledWith({ windowId: 3 });
  });
});
