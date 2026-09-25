/**
 * The extension's service worker.
 *
 * Chrome stops it after half a minute without events, so it holds no state of
 * its own: long work (chat streams, the agent) runs in the side panel, which
 * lives as long as it is open. What is left here is what only a worker can
 * do: react to the toolbar button, the keyboard shortcut and the right-click
 * menu, even when the panel is closed.
 */

import { createMenus, handleMenuClick } from "./lib/menus";

function openThePanelFromTheToolbar(): void {
  // Persisted by Chrome, but set again on every start: cheap, and it keeps a
  // profile that lost the setting (an update, a crash) working. The keyboard
  // shortcut (_execute_action in the manifest) is a click on the button.
  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => undefined);
}

chrome.runtime.onInstalled.addListener(() => {
  openThePanelFromTheToolbar();
  createMenus();
});
// Registered on every start, before anything else: a click that woke the worker must find it.
chrome.contextMenus.onClicked.addListener(handleMenuClick);
openThePanelFromTheToolbar();
