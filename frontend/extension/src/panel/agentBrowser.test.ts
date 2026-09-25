/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { createAgentBrowser } from "./agentBrowser";

let chromeFake: ChromeFake;
const pageCalls: Array<{ tabId: number; method: string; args: unknown }> = [];

beforeEach(() => {
  chromeFake = installChromeFake();
  pageCalls.length = 0;
  chromeFake.scripting.executeScript.mockImplementation(async (injection: unknown) => {
    const { files, target, args } = injection as { files?: string[]; target: { tabId: number }; args?: [string, string, unknown] };
    if (files) return [];
    pageCalls.push({ tabId: target.tabId, method: args![1], args: args![2] });
    return [{ result: { ok: true, note: "Done." } }];
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the browser the agent uses", () => {
  it("works in the tab next to the panel, and puts its banner up once per page", async () => {
    const tab = chromeFake.tabs.add({ url: "https://shop.example.com/cart", title: "Cart", active: true });
    const browser = createAgentBrowser({ startTabId: tab.id!, runId: "run-1" });
    await expect(browser.current()).resolves.toEqual({ id: tab.id, url: "https://shop.example.com/cart", host: "shop.example.com", title: "Cart" });
    await browser.page("read_page");
    await browser.page("click", { ref: "e1" });
    expect(pageCalls.map((c) => c.method)).toEqual(["show_overlay", "read_page", "click"]);
    expect(pageCalls[0].args).toMatchObject({ run: "run-1" });
    // Another page in the same tab: the banner goes up again there.
    chromeFake.tabs.update(tab.id!, { url: "https://shop.example.com/checkout" });
    await browser.page("read_page");
    expect(pageCalls.map((c) => c.method)).toEqual(["show_overlay", "read_page", "click", "show_overlay", "read_page"]);
    await browser.cleanup();
    expect(pageCalls.at(-1)).toMatchObject({ tabId: tab.id, method: "hide_overlay", args: { run: "run-1" } });
  });

  it("puts the tabs it opens in one Alpharouter group, and works in the newest", async () => {
    const start = chromeFake.tabs.add({ url: "https://shop.example.com/", active: true });
    const browser = createAgentBrowser({ startTabId: start.id!, runId: "run-1" });
    const first = await browser.openTab("https://partner.org/a");
    const second = await browser.openTab("https://partner.org/b");
    expect(chromeFake.tabs.groups.get(first.id)).toBe(chromeFake.tabs.groups.get(second.id));
    expect(chromeFake.tabGroups.update).toHaveBeenCalledWith(chromeFake.tabs.groups.get(first.id), { title: "Alpharouter", color: "cyan" });
    expect(chromeFake.tabs.groups.has(start.id!)).toBe(false);
    expect(browser.workingTab()).toBe(second.id);
  });

  it("switches only to a tab of this window", async () => {
    const start = chromeFake.tabs.add({ url: "https://shop.example.com/", active: true });
    const other = chromeFake.tabs.add({ url: "https://docs.example.com/", title: "Docs" });
    const elsewhere = chromeFake.tabs.add({ url: "https://news.example.com/", windowId: 2 });
    const browser = createAgentBrowser({ startTabId: start.id!, runId: "run-1" });
    await expect(browser.switchTab(elsewhere.id!)).resolves.toBeNull();
    await expect(browser.switchTab(other.id!)).resolves.toMatchObject({ id: other.id, host: "docs.example.com" });
    expect(browser.workingTab()).toBe(other.id);
  });

  it("does nothing in a tab that shows no web page", async () => {
    const start = chromeFake.tabs.add({ url: "chrome://newtab/", active: true });
    const browser = createAgentBrowser({ startTabId: start.id!, runId: "run-1" });
    await expect(browser.page("read_page")).resolves.toMatchObject({ ok: false });
    expect(pageCalls).toEqual([]);
  });

  it("knows which sites the browser lets it work on", async () => {
    const browser = createAgentBrowser({ startTabId: null, runId: "run-1" });
    chromeFake.permissions.granted.add("https://shop.example.com/*");
    await expect(browser.hasAccess("https://shop.example.com/cart?x=1")).resolves.toBe(true);
    await expect(browser.hasAccess("https://partner.org/")).resolves.toBe(false);
    await expect(browser.hasAccess("javascript:alert(1)")).resolves.toBe(false);
  });

  it("waits for a page that is loading, but not forever", async () => {
    const start = chromeFake.tabs.add({ url: "https://shop.example.com/", active: true, status: "loading" });
    const browser = createAgentBrowser({ startTabId: start.id!, runId: "run-1" });
    vi.useFakeTimers();
    try {
      let settled = false;
      const waiting = browser.settle().then(() => (settled = true));
      await vi.advanceTimersByTimeAsync(2000);
      expect(settled).toBe(false);
      chromeFake.tabs.update(start.id!, { status: "complete" } as never);
      await vi.advanceTimersByTimeAsync(500);
      await waiting;
      expect(settled).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
