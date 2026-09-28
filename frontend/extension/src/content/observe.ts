/**
 * What the page is like right after one of the agent's actions: where the
 * keyboard is now, and what the page announced meanwhile.
 *
 * A model that clicks a field and types learns from this whether the text
 * went where it meant: the focused element, with its value (never a
 * sensitive field's). And pages say what happened in live regions - "Message
 * sent", "Enter a valid address", a dialog that opened - often for a few
 * seconds only. A watch on the page, started with the run's first call to it,
 * keeps each new announcement until the next look collects it; what the page
 * already said before the agent came is not news.
 */

import { describeFocus, scrolledTo, scrollerFor, scrollerName, type ElementInfo, type Visibility } from "./agent";
import { inOwnUi } from "./own";

/** Where a page announces things, and the dialogs it opens. */
const ANNOUNCERS = '[role="alert"], [role="status"], [aria-live="assertive"], [aria-live="polite"], output, [role="alertdialog"], [role="dialog"], dialog[open]';
/** At most this many announcers are looked at, and this many announcements kept, each this long. */
const MAX_ANNOUNCERS = 60;
const MAX_KEPT = 8;
const ANNOUNCEMENT_CHARS = 200;
/** A burst of changes to the page is looked at once, this long after it starts. */
const SETTLE_MS = 60;

type Announcement = { kind: "alert" | "dialog"; text: string };

type Watch = { last: WeakMap<Element, string>; kept: Announcement[]; timer: number | null; isVisible: Visibility; observer?: MutationObserver };

const WATCH_KEY = "__alpharouterAnnouncements";

/** Each document's watch, kept in the isolated world (the page cannot reach it) across injections of content.js. */
function watches(): WeakMap<Document, Watch> {
  const scope = globalThis as typeof globalThis & { [WATCH_KEY]?: WeakMap<Document, Watch> };
  const found = scope[WATCH_KEY];
  if (found instanceof WeakMap) return found;
  const fresh = new WeakMap<Document, Watch>();
  scope[WATCH_KEY] = fresh;
  return fresh;
}

function squash(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function parentOf(el: Element): Element | null {
  if (el.parentElement) return el.parentElement;
  const root = el.getRootNode();
  return root instanceof ShadowRoot ? root.host : null;
}

/** Shown to a person: the element and everything it sits in. */
function shown(el: Element, isVisible: Visibility): boolean {
  for (let node: Element | null = el, depth = 0; node && depth < 40; node = parentOf(node), depth += 1) {
    if (!isVisible(node)) return false;
  }
  return true;
}

function kindOf(el: Element): Announcement["kind"] {
  const role = (el.getAttribute("role") ?? "").trim().toLowerCase();
  return role === "dialog" || role === "alertdialog" || el.tagName.toUpperCase() === "DIALOG" ? "dialog" : "alert";
}

/** The words an announcer shows now: a dialog by its name (its label, or its first words), the rest by what they say. */
function wordsOf(el: Element): string {
  if (kindOf(el) === "dialog") {
    const label = squash(el.getAttribute("aria-label") ?? "");
    const by = (el.getAttribute("aria-labelledby") ?? "").split(/\s+/).filter(Boolean);
    const named = label || squash(by.map((id) => el.ownerDocument.getElementById(id)?.textContent ?? "").join(" "));
    if (named) return named;
  }
  return squash((el as HTMLElement).innerText ?? el.textContent ?? "");
}

/** Look at the page's announcers; what one says that it did not say last time is kept (unless this is the first look, which only notes). */
function scan(doc: Document, watch: Watch, keep: boolean): void {
  const found = Array.from(doc.querySelectorAll(ANNOUNCERS)).slice(0, MAX_ANNOUNCERS);
  for (const el of found) {
    if (inOwnUi(el)) continue;
    const words = shown(el, watch.isVisible) ? wordsOf(el).slice(0, ANNOUNCEMENT_CHARS) : "";
    if (watch.last.get(el) === words) continue;
    watch.last.set(el, words);
    if (!keep || !words) continue;
    watch.kept.push({ kind: kindOf(el), text: words });
    if (watch.kept.length > MAX_KEPT) watch.kept.shift();
  }
}

/**
 * Start watching what `doc` announces, once: from now on each new
 * announcement is kept for the next look. What the page says already is
 * noted as it is, not kept.
 */
export function watchAnnouncements(doc: Document, isVisible: Visibility): void {
  const all = watches();
  if (all.has(doc)) return;
  const watch: Watch = { last: new WeakMap(), kept: [], timer: null, isVisible };
  all.set(doc, watch);
  scan(doc, watch, false);
  const view = doc.defaultView;
  if (!view || typeof view.MutationObserver !== "function") return;
  const observer = new view.MutationObserver(() => {
    if (watch.timer !== null) return;
    watch.timer = view.setTimeout(() => {
      watch.timer = null;
      scan(doc, watch, true);
    }, SETTLE_MS);
  });
  observer.observe(doc.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["open", "hidden", "style", "class", "aria-hidden"] });
  watch.observer = observer;
}

/** The run is over on this page: the watch goes, with what it kept. */
export function stopAnnouncements(doc: Document): void {
  const watch = watches().get(doc);
  if (!watch) return;
  watch.observer?.disconnect();
  if (watch.timer !== null) doc.defaultView?.clearTimeout(watch.timer);
  watches().delete(doc);
}

/** The window and the page, in CSS pixels: how much of the page the window shows, and where it is scrolled to. */
type View = { width: number; height: number; scrollX: number; scrollY: number; pageWidth: number; pageHeight: number };

export type Observation = { focus?: ElementInfo; said: Announcement[]; view?: View; scrolled?: string };

function viewOf(doc: Document): View | undefined {
  const win = doc.defaultView;
  const scroller = doc.scrollingElement ?? doc.documentElement;
  if (!win || !scroller) return undefined;
  const round = (value: number) => Math.max(0, Math.round(Number.isFinite(value) ? value : 0));
  return {
    width: round(win.innerWidth),
    height: round(win.innerHeight),
    scrollX: round(win.scrollX),
    scrollY: round(win.scrollY),
    pageWidth: round(Math.max(scroller.scrollWidth, win.innerWidth)),
    pageHeight: round(Math.max(scroller.scrollHeight, win.innerHeight)),
  };
}

/** What scrolls under a point (a list, or the page), and where it is now: after the wheel turned there. */
function scrolledAt(doc: Document, at: unknown): string | undefined {
  const p = at && typeof at === "object" ? (at as Record<string, unknown>) : null;
  if (!p || typeof p.x !== "number" || typeof p.y !== "number" || typeof doc.elementFromPoint !== "function") return undefined;
  const scroller = scrollerFor(doc, doc.elementFromPoint(p.x, p.y), "y");
  return scroller ? `${scrollerName(doc, scroller)} is ${scrolledTo(doc, scroller, "y")}` : undefined;
}

/**
 * The page now: the element with the keyboard, what the page announced since
 * the last look (collected, so said once), the window's view of it - and,
 * given a point, where what scrolls under it is.
 */
export function observe(doc: Document, isVisible: Visibility, at?: unknown): Observation {
  watchAnnouncements(doc, isVisible);
  const watch = watches().get(doc)!;
  scan(doc, watch, true);
  const said = watch.kept.splice(0);
  const focus = describeFocus(doc, isVisible);
  const view = viewOf(doc);
  const scrolled = scrolledAt(doc, at);
  return { ...(focus.ok && focus.element ? { focus: focus.element } : {}), said, ...(view ? { view } : {}), ...(scrolled ? { scrolled } : {}) };
}
