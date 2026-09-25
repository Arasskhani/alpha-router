/**
 * Other tabs the user adds to a question, next to "This page": chosen from a
 * list, or by typing @ and part of a tab's title in the composer.
 *
 * Each goes with the next question only, and only while it stays on the site
 * it was chosen on: a tab that closes or moves to another site drops out.
 * Reading one needs Chrome's permission for its site, asked for in the click
 * or key press that adds it.
 */

import { useCallback, useEffect, useState } from "react";

import { readablePage, type ReadablePage } from "../lib/sites";

/** Other tabs one question may carry, besides the page next to the panel. */
export const MAX_OTHER_TABS = 4;

export type ChosenTab = { tabId: number; url: string; title: string; target: ReadablePage };

/** A tab the list offers, and whether Chrome already lets the extension read its site. */
export type PickableTab = ChosenTab & { granted: boolean };

/** An "@part" being typed just before the caret, to pick a tab with. */
export function mentionAt(text: string, caret: number): { start: number; query: string } | null {
  const match = /(^|\s)@([^\s@]{0,60})$/.exec(text.slice(0, caret));
  return match ? { start: caret - match[2].length - 1, query: match[2] } : null;
}

/** The tabs of this window the list can offer: readable pages, not `excluded` (the page next to the panel, those chosen). */
export async function tabCandidates(excluded: Set<number>): Promise<PickableTab[]> {
  const [tabs, permissions] = await Promise.all([
    chrome.tabs.query({ currentWindow: true }),
    chrome.permissions.getAll(),
  ]);
  const origins = new Set(permissions.origins ?? []);
  const out: PickableTab[] = [];
  for (const tab of tabs) {
    const target = readablePage(tab.url);
    if (tab.id === undefined || !target || excluded.has(tab.id)) continue;
    out.push({
      tabId: tab.id,
      url: tab.url ?? "",
      title: (tab.title ?? "").trim() || target.host,
      target,
      granted: origins.has("<all_urls>") || origins.has(target.pattern),
    });
  }
  return out;
}

/** Tabs that match what the user typed, by title or site. */
export function matchingTabs(tabs: PickableTab[], query: string): PickableTab[] {
  const q = query.trim().toLowerCase();
  return q ? tabs.filter((tab) => `${tab.title} ${tab.target.host}`.toLowerCase().includes(q)) : tabs;
}

/** The tabs chosen for the next question, kept to those still open on the site they were chosen on. */
export function useChosenTabs() {
  const [chosen, setChosen] = useState<ChosenTab[]>([]);

  useEffect(() => {
    const onRemoved = (tabId: number) => setChosen((all) => (all.some((t) => t.tabId === tabId) ? all.filter((t) => t.tabId !== tabId) : all));
    const onUpdated = (tabId: number, change: chrome.tabs.OnUpdatedInfo) => {
      setChosen((all) => {
        const tab = all.find((t) => t.tabId === tabId);
        if (!tab) return all;
        if (change.url !== undefined && readablePage(change.url)?.origin !== tab.target.origin) {
          return all.filter((t) => t.tabId !== tabId);
        }
        if (change.url !== undefined || change.title !== undefined) {
          return all.map((t) =>
            t.tabId === tabId ? { ...t, url: change.url ?? t.url, title: change.title?.trim() || t.title } : t,
          );
        }
        return all;
      });
    };
    chrome.tabs.onRemoved.addListener(onRemoved);
    chrome.tabs.onUpdated.addListener(onUpdated);
    return () => {
      chrome.tabs.onRemoved.removeListener(onRemoved);
      chrome.tabs.onUpdated.removeListener(onUpdated);
    };
  }, []);

  const add = useCallback(
    (tab: ChosenTab) =>
      setChosen((all) =>
        all.some((t) => t.tabId === tab.tabId) || all.length >= MAX_OTHER_TABS
          ? all
          : [...all, { tabId: tab.tabId, url: tab.url, title: tab.title, target: tab.target }],
      ),
    [],
  );
  const remove = useCallback((tabId: number) => setChosen((all) => all.filter((t) => t.tabId !== tabId)), []);
  const clear = useCallback(() => setChosen([]), []);

  return { chosen, add, remove, clear };
}
