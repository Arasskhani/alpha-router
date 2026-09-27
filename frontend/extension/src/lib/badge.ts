/**
 * The toolbar badge while the agent runs: a dot on the extension's button, in
 * the colour of the run's state, so a person sees from any tab that the agent
 * is working, waiting for them, or paused. It goes with the run - and, should
 * the panel close without a word, with the panel (background.ts).
 */

export type BadgeState = "working" | "waiting" | "paused";

const COLOR: Record<BadgeState, string> = {
  working: "#2eaadc", // brand cyan
  waiting: "#ffb347", // amber
  paused: "#969696", // grey
};

const TITLE: Record<BadgeState, string> = {
  working: "Alpharouter: the agent is working",
  waiting: "Alpharouter: the agent is waiting for you",
  paused: "Alpharouter: the agent is paused - you took over",
};

const DEFAULT_TITLE = "Open Alpharouter";

/** Best-effort: a badge that cannot be set is not the run's problem. */
export async function showBadge(state: BadgeState): Promise<void> {
  try {
    // A badge needs text to show at all; in the badge's own colour the glyph disappears, leaving a plain pill of that colour.
    await chrome.action.setBadgeText({ text: "\u25CF" });
    await chrome.action.setBadgeBackgroundColor({ color: COLOR[state] });
    await chrome.action.setBadgeTextColor({ color: COLOR[state] });
    await chrome.action.setTitle({ title: TITLE[state] });
  } catch {
    // No action API here, or no permission: the panel and the page still show the state.
  }
}

export async function clearBadge(): Promise<void> {
  try {
    await chrome.action.setBadgeText({ text: "" });
    await chrome.action.setTitle({ title: DEFAULT_TITLE });
  } catch {
    // As above.
  }
}
