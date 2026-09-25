/**
 * Screenshots of the tab next to the panel. Chrome takes one only with
 * access to every site, or for the tab a right-click (or the shortcut) was
 * made in (activeTab): a per-site grant is not enough.
 */

/** A JPEG: small enough to send with a question, sharp enough to read. */
const OPTIONS: chrome.extensionTypes.ImageDetails = { format: "jpeg", quality: 80 };

/** The visible part of the active tab in a window, as a data URL. */
export function captureTab(windowId: number): Promise<string> {
  return chrome.tabs.captureVisibleTab(windowId, OPTIONS);
}
