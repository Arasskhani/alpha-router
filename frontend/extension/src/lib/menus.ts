/**
 * The right-click menu: summarize the page, or explain, translate or ask
 * about the selection. Each item opens the side panel and leaves the work
 * there (see pendingAction.ts).
 *
 * A click on one of them also grants the extension that tab for as long as it
 * shows the same page (Chrome's activeTab), so it works on a site the user has
 * not granted yet, without a prompt.
 */

import { broadcast } from "./messages";
import { MAX_SELECTION_CHARS } from "./pageContext";
import { savePendingAction, type PendingActionKind } from "./pendingAction";

const WEB_PAGES = ["http://*/*", "https://*/*"];

type MenuItem = { id: string; kind: PendingActionKind; title: string; on: "page" | "selection" };

const MENU_ITEMS: MenuItem[] = [
  { id: "alpharouter-summarize", kind: "summarize", title: "Summarize this page", on: "page" },
  { id: "alpharouter-explain", kind: "explain", title: "Explain “%s”", on: "selection" },
  { id: "alpharouter-translate", kind: "translate", title: "Translate “%s” to Persian", on: "selection" },
  { id: "alpharouter-ask", kind: "ask", title: "Ask Alpharouter about “%s”", on: "selection" },
];

/** Chrome keeps menus across worker restarts, so they are made once, on install or update. */
export function createMenus(): void {
  chrome.contextMenus.removeAll(() => {
    for (const item of MENU_ITEMS) {
      chrome.contextMenus.create({ id: item.id, title: item.title, contexts: [item.on], documentUrlPatterns: WEB_PAGES });
    }
  });
}

export function handleMenuClick(info: chrome.contextMenus.OnClickData, tab?: chrome.tabs.Tab): void {
  const item = MENU_ITEMS.find((entry) => entry.id === info.menuItemId);
  if (!item || tab?.id === undefined || tab.windowId === undefined || tab.windowId < 0) return;
  // First, while Chrome still counts the click as the user's: nothing may come before it.
  chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => undefined);
  const onSelection = item.on === "selection";
  // Text selected inside a frame comes from the frame's page, which can be
  // another site than the tab's: the site rules and the label go by where the
  // text came from, and the tab's title is not its title.
  const fromFrame = onSelection && Boolean(info.frameUrl) && info.frameUrl !== info.pageUrl;
  // One character past what the model is sent, so the panel can tell it the text was cut.
  const selection = onSelection ? (info.selectionText ?? "").slice(0, MAX_SELECTION_CHARS + 1) : "";
  void savePendingAction({
    id: crypto.randomUUID(),
    kind: item.kind,
    tabId: tab.id,
    windowId: tab.windowId,
    pageUrl: (fromFrame ? info.frameUrl : info.pageUrl) || tab.url || "",
    title: fromFrame ? "" : (tab.title ?? ""),
    selection,
    createdAt: Date.now(),
  }).then(() => broadcast({ type: "pending-action" }));
}
