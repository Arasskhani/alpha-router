/**
 * Work the service worker leaves for the side panel.
 *
 * A right-click action has to open the panel while Chrome still counts the
 * click as the user's, and the worker cannot run a chat (Chrome stops it
 * after half a minute idle), so it writes down what was asked and the panel
 * does it. The note lives in storage.session, names the window it was made
 * in, is taken exactly once, and goes stale after two minutes.
 */

export type PendingActionKind = "summarize" | "explain" | "translate" | "ask" | "screenshot";

export type PendingAction = {
  id: string;
  kind: PendingActionKind;
  tabId: number;
  windowId: number;
  /** The page the action is about; for a selection, the page (or frame) the text was selected in. */
  pageUrl: string;
  title: string;
  /** The selected text, for the actions on a selection; empty otherwise. */
  selection: string;
  /** For a screenshot: the image, as a data URL; empty when Chrome would not take it. */
  image?: string;
  createdAt: number;
};

const KEY = "alpharouter.pending-action";
export const PENDING_ACTION_MAX_AGE_MS = 2 * 60_000;
const KINDS = new Set<PendingActionKind>(["summarize", "explain", "translate", "ask", "screenshot"]);
/** More than any screenshot the worker takes. */
const MAX_IMAGE_CHARS = 8_000_000;

export async function savePendingAction(action: PendingAction): Promise<void> {
  await chrome.storage.session.set({ [KEY]: action });
}

function parse(value: unknown): PendingAction | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  const numbers = [v.tabId, v.windowId, v.createdAt].every((n) => typeof n === "number" && Number.isFinite(n));
  const strings = [v.id, v.pageUrl, v.title, v.selection].every((s) => typeof s === "string");
  if (!numbers || !strings || !KINDS.has(v.kind as PendingActionKind)) return null;
  if (v.image !== undefined && (typeof v.image !== "string" || v.image.length > MAX_IMAGE_CHARS)) return null;
  return v as unknown as PendingAction;
}

/**
 * The action waiting for this window's panel, taken so no one runs it twice.
 * Another window's action stays for that window.
 */
export async function takePendingAction(windowId: number, now = Date.now()): Promise<PendingAction | null> {
  const action = parse((await chrome.storage.session.get(KEY))[KEY]);
  if (action && action.windowId !== windowId) return null;
  await chrome.storage.session.remove(KEY);
  if (!action) return null;
  const age = now - action.createdAt;
  return age >= 0 && age <= PENDING_ACTION_MAX_AGE_MS ? action : null;
}
