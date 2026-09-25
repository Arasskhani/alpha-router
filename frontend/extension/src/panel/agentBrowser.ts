/**
 * The browser as the agent's loop uses it (agentRun.ts): the tab it works in,
 * the other tabs of the panel's window, and the page actions of content.js.
 *
 * Tabs the agent opens go into one "Alpharouter" tab group, so the user sees
 * which tabs are its work. Its banner with Stop is put on each page it works
 * in, and taken off every one of them when the run ends.
 */

import { callPage, type OverlayRequest, type PageMethod, type PageResult, type PageTarget } from "../lib/pageAgent";
import { readablePage } from "../lib/sites";
import type { AgentBrowser, WorkTab } from "./agentRun";

/** How long a page may take to load after an action before the agent looks anyway. */
const SETTLE_LIMIT_MS = 10_000;
const SETTLE_POLL_MS = 250;
/** Time for a click or a key to start loading a page, if it is going to. */
const SETTLE_START_MS = 400;
const OVERLAY_LABEL = "Alpharouter is working on this page";

function workTab(tab: chrome.tabs.Tab | undefined): WorkTab | null {
  if (!tab || tab.id === undefined) return null;
  return { id: tab.id, url: tab.url ?? "", host: readablePage(tab.url)?.host ?? null, title: tab.title ?? "" };
}

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));

/** The page in a tab as a call's target; null when it is no web page. */
function targetOf(tab: WorkTab): PageTarget | null {
  const page = tab.host ? readablePage(tab.url) : null;
  return page ? { tabId: tab.id, host: page.host, origin: page.origin } : null;
}

export type PanelBrowser = AgentBrowser & {
  /** The tab the agent works in now. */
  workingTab(): number | null;
  /** Every tab the run put its banner on: a Stop from any of them stops the run. */
  bannerTabs(): number[];
  /** Take the banner off every page it was put on. */
  cleanup(): Promise<void>;
};

export function createAgentBrowser(options: { startTabId: number | null; runId: string; windowId?: number }): PanelBrowser {
  let working = options.startTabId;
  let groupId: number | null = null;
  /** Where the banner went up: tab id → the page it was put on. */
  const overlays = new Map<number, PageTarget>();
  const banner: OverlayRequest = { run: options.runId, label: OVERLAY_LABEL };

  async function current(): Promise<WorkTab | null> {
    if (working === null) return null;
    return workTab(await chrome.tabs.get(working).catch(() => undefined));
  }

  async function inWindow(tabId: number): Promise<chrome.tabs.Tab | undefined> {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    return tabs.find((tab) => tab.id === tabId);
  }

  async function group(tabId: number): Promise<void> {
    try {
      if (groupId === null) {
        groupId = await chrome.tabs.group({ tabIds: [tabId] });
        await chrome.tabGroups.update(groupId, { title: "Alpharouter", color: "cyan" });
      } else {
        await chrome.tabs.group({ groupId, tabIds: [tabId] });
      }
    } catch {
      // A group is a courtesy: a browser or window without them still works.
      groupId = null;
    }
  }

  /** Take the banner off a tab the agent no longer works in, so no banner claims a tab the run has left. */
  function leave(tabId: number | null): void {
    const where = tabId === null ? undefined : overlays.get(tabId);
    if (tabId === null || !where) return;
    overlays.delete(tabId);
    void callPage(where, "hide_overlay", { run: options.runId }).catch(() => undefined);
  }

  return {
    current,
    workingTab: () => working,
    bannerTabs: () => [...overlays.keys()],

    async listTabs() {
      const tabs = await chrome.tabs.query({ currentWindow: true });
      return tabs.flatMap((tab) => {
        const info = workTab(tab);
        return info ? [{ ...info, active: Boolean(tab.active) }] : [];
      });
    },

    async openTab(url: string) {
      const tab = await chrome.tabs.create({ url, active: true });
      if (tab.id === undefined) throw new Error("The browser did not open the tab.");
      leave(working);
      working = tab.id;
      await group(tab.id);
      return workTab(tab) ?? { id: tab.id, url, host: readablePage(url)?.host ?? null, title: "" };
    },

    async switchTab(tabId: number) {
      if (!Number.isInteger(tabId) || !(await inWindow(tabId))) return null;
      const tab = await chrome.tabs.update(tabId, { active: true });
      if (working !== tabId) leave(working);
      working = tabId;
      return workTab(tab) ?? current();
    },

    async navigate(url: string) {
      if (working === null) throw new Error("There is no tab to open the page in.");
      const tab = await chrome.tabs.update(working, { url });
      return workTab(tab) ?? { id: working, url, host: readablePage(url)?.host ?? null, title: "" };
    },

    async page(method: PageMethod, args: Record<string, unknown> = {}, judged?: WorkTab): Promise<PageResult> {
      const tab = await current();
      const target = tab ? targetOf(tab) : null;
      if (!tab || !target) return { ok: false, error: "failed", message: "The tab does not show a web page the agent can work on." };
      // Only on the page the rules judged: the tab may have gone to another site since.
      const expected = judged ? targetOf(judged) : target;
      if (!expected || expected.tabId !== target.tabId || expected.origin !== target.origin) {
        return { ok: false, error: "moved", message: "The tab went to another page since the agent looked. Read the page again." };
      }
      // The banner goes up with every action: a page that took it down gets it back.
      overlays.set(tab.id, expected);
      return callPage(expected, method, args, banner);
    },

    async hasAccess(url: string) {
      const page = readablePage(url);
      if (!page) return false;
      return chrome.permissions.contains({ origins: [page.pattern] }).catch(() => false);
    },

    async settle() {
      await sleep(SETTLE_START_MS);
      const deadline = Date.now() + SETTLE_LIMIT_MS;
      while (working !== null && Date.now() < deadline) {
        const tab = await chrome.tabs.get(working).catch(() => undefined);
        if (!tab || tab.status !== "loading") return;
        await sleep(SETTLE_POLL_MS);
      }
    },

    async cleanup() {
      await Promise.all(
        [...overlays.values()].map((where) => callPage(where, "hide_overlay", { run: options.runId }).catch(() => undefined)),
      );
      overlays.clear();
    },
  };
}
