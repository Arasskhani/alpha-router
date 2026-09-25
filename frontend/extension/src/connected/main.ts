import { getClient } from "../lib/client";
import { serverUrl } from "../lib/config";
import { runConnectedPage } from "./page";

void runConnectedPage(document, window.location, window.history, {
  tokens: getClient().tokens,
  serverUrl,
  fetch: (input, init) => fetch(input, init),
  setTimeout: (fn, ms) => void window.setTimeout(fn, ms),
  closeTab: () => {
    chrome.tabs.getCurrent((tab) => {
      if (tab?.id !== undefined) void chrome.tabs.remove(tab.id).catch(() => undefined);
    });
  },
});
