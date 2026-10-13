/**
 * The browser as the agent's loop uses it (agentRun.ts): the tab it works in,
 * the other tabs of the panel's window, and the page actions of content.js.
 *
 * The tabs the agent works in go into one "Alpharouter" tab group, so the user
 * sees which tabs are its work: the tab the run starts in and any it switches
 * to for as long as the run lasts (each goes back to its own group, or to
 * none, when the run ends), and the tabs it opens, which stay in the group.
 * Its banner with Stop is put on each page it works in, and taken off every
 * one of them when the run ends.
 */

import { callPage, type OverlayRequest, type PageMethod, type PageResult, type PageTarget } from "../lib/pageAgent";
import { readablePage } from "../lib/sites";
import type { AgentBrowser, WorkTab } from "./agentRun";

/** How long a page may take to load after an action before the agent looks anyway. */
const SETTLE_LIMIT_MS = 10_000;
const SETTLE_POLL_MS = 250;
/** Time for a click or a key to start loading a page, if it is going to: the tab says so, or the step goes on. */
const SETTLE_WATCH_MS = 200;
const OVERLAY_LABEL = "Alpharouter is working on this page";
/** Taking the banner off a page at the end of a run: best-effort, and not for long. */
const CLEANUP_MS = 2000;

/** Whether the tab is loading a page, or starts to within SETTLE_WATCH_MS. */
function loadStarts(tabId: number): Promise<boolean> {
  return new Promise((resolve) => {
    let over = false;
    const finish = (loading: boolean) => {
      if (over) return;
      over = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listen);
      resolve(loading);
    };
    const listen = (id: number, change: { status?: string; url?: string }) => {
      if (id === tabId && (change.status === "loading" || change.url !== undefined)) finish(true);
    };
    chrome.tabs.onUpdated.addListener(listen);
    const timer = setTimeout(() => finish(false), SETTLE_WATCH_MS);
    chrome.tabs.get(tabId).then(
      (tab) => {
        if (tab?.status === "loading") finish(true);
      },
      () => finish(false),
    );
  });
}

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
  /** Take the banner off every page it was put on, and give the tabs the run took back to their own groups. */
  cleanup(): Promise<void>;
};

/** Tabs one run may open when the administrator set no limit. */
const DEFAULT_MAX_TABS = 10;

/** The highest element reference a page's answer names ("e41" in an outline or an element), or 0. */
function highestRef(result: unknown): number {
  let highest = 0;
  let text = "";
  try {
    text = JSON.stringify(result) ?? "";
  } catch {
    return 0;
  }
  for (const match of text.matchAll(/(?<![\w-])e(\d{1,9})(?![\w-])/g)) highest = Math.max(highest, Number(match[1]));
  return highest;
}

export function createAgentBrowser(options: { startTabId: number | null; runId: string; windowId?: number; maxTabs?: number }): PanelBrowser {
  let working = options.startTabId;
  let groupId: number | null = null;
  /** Tabs the run took into its group though it did not open them: tab id → the group each was in (-1 for none). */
  const adopted = new Map<number, number>();
  const maxTabs = Math.max(1, Math.floor(options.maxTabs ?? DEFAULT_MAX_TABS));
  let opened = 0;
  /** Where the banner went up: tab id → the page it was put on. */
  const overlays = new Map<number, PageTarget>();
  // `since`: a page loaded after the run began says nothing old - what it shows first is news (an order placed).
  const banner: OverlayRequest = { run: options.runId, label: OVERLAY_LABEL, since: Date.now() };
  /**
   * The first reference a page may give next: past every one this run was
   * told, on any page. A page reached later numbers its elements from there,
   * so e3 of the page before never names an element of this one.
   */
  let refsFrom = 1;
  /** While this says so, a page call is not given up on (see holdWhile). */
  let hold: (() => boolean) | undefined;

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

  /**
   * A tab the user had, now the agent's for the run: into the group, with the
   * group it was in remembered so the end of the run gives it back.
   */
  async function adopt(tabId: number): Promise<void> {
    if (adopted.has(tabId)) return;
    const tab = await chrome.tabs.get(tabId).catch(() => undefined);
    if (!tab || tab.id === undefined) return;
    // Already in the run's group: a tab the agent opened, which stays there.
    if (groupId !== null && tab.groupId === groupId) return;
    adopted.set(tabId, typeof tab.groupId === "number" ? tab.groupId : -1);
    await group(tabId);
  }

  /** Every tab the run took goes back to the group it was in, or out of any; best-effort. */
  async function giveBack(): Promise<void> {
    const back = [...adopted.entries()];
    adopted.clear();
    await Promise.all(
      back.map(async ([tabId, was]) => {
        try {
          if (was >= 0) await chrome.tabs.group({ groupId: was, tabIds: [tabId] });
          else await chrome.tabs.ungroup([tabId]);
        } catch {
          // The tab is gone, or its old group is: out of the run's group at least.
          await chrome.tabs.ungroup([tabId]).catch(() => undefined);
        }
      }),
    );
  }

  /** Take the banner off a tab the agent no longer works in, so no banner claims a tab the run has left. */
  function leave(tabId: number | null): void {
    const where = tabId === null ? undefined : overlays.get(tabId);
    if (tabId === null || !where) return;
    overlays.delete(tabId);
    void callPage(where, "hide_overlay", { run: options.runId }, null, undefined, CLEANUP_MS).catch(() => undefined);
  }

  return {
    current,
    async begin() {
      if (working !== null) await adopt(working);
    },
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
      // The administrator's limit on tabs a run opens: past it, the agent works in the tabs it has.
      if (opened >= maxTabs) throw new Error(`This run may open at most ${maxTabs} tabs. Work in the tabs you have, or switch to one.`);
      opened += 1;
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
      await adopt(tabId);
      return workTab(tab) ?? current();
    },

    async navigate(url: string) {
      if (working === null) throw new Error("There is no tab to open the page in.");
      const tab = await chrome.tabs.update(working, { url });
      return workTab(tab) ?? { id: working, url, host: readablePage(url)?.host ?? null, title: "" };
    },

    holdWhile(when: () => boolean) {
      hold = when;
    },

    async page(method: PageMethod, args: Record<string, unknown> = {}, judged?: WorkTab, signal?: AbortSignal, timeoutMs?: number): Promise<PageResult> {
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
      const result = await callPage(expected, method, args, { ...banner, refsFrom }, signal, timeoutMs, hold);
      refsFrom = Math.max(refsFrom, highestRef(result) + 1);
      return result;
    },

    async hasAccess(url: string) {
      const page = readablePage(url);
      if (!page) return false;
      return chrome.permissions.contains({ origins: [page.pattern] }).catch(() => false);
    },

    async settle() {
      if (working === null) return;
      if (!(await loadStarts(working))) return;
      const deadline = Date.now() + SETTLE_LIMIT_MS;
      while (working !== null && Date.now() < deadline) {
        const tab = await chrome.tabs.get(working).catch(() => undefined);
        if (!tab || tab.status !== "loading") return;
        await sleep(SETTLE_POLL_MS);
      }
    },

    async cleanup() {
      await Promise.all([
        ...[...overlays.values()].map((where) => callPage(where, "hide_overlay", { run: options.runId }, null, undefined, CLEANUP_MS).catch(() => undefined)),
        giveBack(),
      ]);
      overlays.clear();
    },
  };
}
