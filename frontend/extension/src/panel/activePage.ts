/**
 * The page the user is looking at, next to the panel, and whether Chrome
 * lets the extension read it.
 *
 * Both are kept current from Chrome's events rather than asked for on click:
 * Chrome shows its permission prompt only while a click is being handled, so
 * the click must be able to ask at once, with nothing to wait for first.
 */

import { useEffect, useState } from "react";

import { readablePage, type ReadablePage } from "../lib/sites";

export type ActivePage = {
  tabId: number;
  url: string;
  title: string;
  /** Null for pages the extension can never read (chrome://, the web store, files). */
  target: ReadablePage | null;
};

export function useActivePage(): ActivePage | null {
  const [page, setPage] = useState<ActivePage | null>(null);

  useEffect(() => {
    let active = true;
    const refresh = () => {
      chrome.tabs
        .query({ active: true, currentWindow: true })
        .then(([tab]) => {
          if (!active) return;
          setPage(
            tab?.id === undefined
              ? null
              : { tabId: tab.id, url: tab.url ?? "", title: tab.title ?? "", target: readablePage(tab.url) },
          );
        })
        .catch(() => undefined);
    };
    const onUpdated = (_tabId: number, change: chrome.tabs.OnUpdatedInfo, tab: chrome.tabs.Tab) => {
      if (tab.active && (change.url !== undefined || change.title !== undefined)) refresh();
    };
    refresh();
    chrome.tabs.onActivated.addListener(refresh);
    chrome.tabs.onUpdated.addListener(onUpdated);
    return () => {
      active = false;
      chrome.tabs.onActivated.removeListener(refresh);
      chrome.tabs.onUpdated.removeListener(onUpdated);
    };
  }, []);

  return page;
}

/** Has Chrome granted the extension this site (per-site grant, or all sites)? Null while asking. */
export function useSiteAccess(pattern: string | null): boolean | null {
  const [known, setKnown] = useState<{ pattern: string; granted: boolean } | null>(null);

  useEffect(() => {
    if (!pattern) return;
    let active = true;
    const check = () => {
      chrome.permissions
        .contains({ origins: [pattern] })
        .then((granted) => {
          if (active) setKnown({ pattern, granted });
        })
        .catch(() => undefined);
    };
    check();
    chrome.permissions.onAdded.addListener(check);
    chrome.permissions.onRemoved.addListener(check);
    return () => {
      active = false;
      chrome.permissions.onAdded.removeListener(check);
      chrome.permissions.onRemoved.removeListener(check);
    };
  }, [pattern]);

  return pattern && known?.pattern === pattern ? known.granted : null;
}
