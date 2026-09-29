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
/** At most this many announcers are noted when the watch starts, or looked at after one burst of changes. */
const MAX_NOTED = 200;
const MAX_TOUCHED = 60;
/** At most this many announcements are kept, each this long. */
const MAX_KEPT = 8;
const ANNOUNCEMENT_CHARS = 200;
/** Changes to the page are looked at as they come, but no more often than this: an animation changes it every frame. */
const SETTLE_MS = 250;

type Announcement = { kind: "alert" | "dialog"; text: string };

type Watch = {
  last: WeakMap<Element, string>;
  kept: Announcement[];
  /** The announcers the page changed since they were last looked at. */
  touched: Set<Element>;
  timer: number | null;
  /** When the changes were last looked at (Date.now()). */
  looked: number;
  isVisible: Visibility;
  observer?: MutationObserver;
};

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

/** Look at these announcers; what one says that it did not say last time is kept (unless `keep` is off, which only notes). */
function scan(watch: Watch, announcers: Iterable<Element>, keep: boolean): void {
  for (const el of announcers) {
    if (inOwnUi(el)) continue;
    const words = el.isConnected && shown(el, watch.isVisible) ? wordsOf(el).slice(0, ANNOUNCEMENT_CHARS) : "";
    if (watch.last.get(el) === words) continue;
    watch.last.set(el, words);
    if (!keep || !words) continue;
    watch.kept.push({ kind: kindOf(el), text: words });
    if (watch.kept.length > MAX_KEPT) watch.kept.shift();
  }
}

/** The announcers one change of the page may have changed: the one it is in, and the ones it added or showed. */
function touchedBy(record: MutationRecord, into: Set<Element>): void {
  const node = record.target;
  const el = node instanceof Element ? node : node.parentElement;
  if (!el) return;
  const around = el.closest(ANNOUNCERS);
  if (around) into.add(around);
  const roots = record.type === "childList" ? Array.from(record.addedNodes) : record.type === "attributes" ? [el] : [];
  for (const root of roots) {
    if (!(root instanceof Element)) continue;
    if (root.matches(ANNOUNCERS)) into.add(root);
    for (const inner of Array.from(root.querySelectorAll(ANNOUNCERS)).slice(0, 20)) into.add(inner);
  }
}

/** Look at what the page changed since the last look, and forget it. */
function flush(watch: Watch): void {
  watch.looked = Date.now();
  // So many at a time; the rest wait for the next look - never dropped (a toast after 60 re-rendered badges).
  const all = Array.from(watch.touched);
  watch.touched = new Set(all.slice(MAX_TOUCHED));
  scan(watch, all.slice(0, MAX_TOUCHED), true);
}

/** Look at every change noted so far: an agent's look takes all of them, a few bursts at a time. */
function flushAll(watch: Watch): void {
  for (let round = 0; watch.touched.size && round < 20; round += 1) flush(watch);
}

/**
 * Start watching what `doc` announces, once: from now on each new
 * announcement is kept for the next look. What the page says already is
 * noted as it is, not kept - unless the page was loaded after `since`, the
 * moment the run began: then it came as the agent's doing (a page that says
 * "Your order was placed" after a form was sent), and what it shows is news.
 */
export function watchAnnouncements(doc: Document, isVisible: Visibility, since?: number): void {
  const all = watches();
  if (all.has(doc)) return;
  const watch: Watch = { last: new WeakMap(), kept: [], touched: new Set(), timer: null, looked: -Infinity, isVisible };
  all.set(doc, watch);
  const view = doc.defaultView;
  const loaded = view?.performance?.timeOrigin;
  const fresh = since !== undefined && typeof loaded === "number" && loaded > since;
  scan(watch, Array.from(doc.querySelectorAll(ANNOUNCERS)).slice(0, MAX_NOTED), fresh);
  if (!view || typeof view.MutationObserver !== "function") return;
  const observer = new view.MutationObserver((records) => {
    for (const record of records) touchedBy(record, watch.touched);
    if (watch.timer !== null || !watch.touched.size) return;
    // A toast that shows for a moment is read as it comes; a page changing all the time, at most every SETTLE_MS.
    const wait = watch.looked + SETTLE_MS - Date.now();
    if (wait <= 0) {
      flush(watch);
      if (!watch.touched.size) return;
    }
    const later = () => {
      watch.timer = null;
      flush(watch);
      // What a burst left for later is looked at once this one has been.
      if (watch.touched.size) watch.timer = view.setTimeout(later, SETTLE_MS);
    };
    // Now after a look just made (the rest of its burst), or the rest of the wait since the last one.
    watch.timer = view.setTimeout(later, wait > 0 ? wait : SETTLE_MS);
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
  // The changes the page made since its last burst was looked at: records not yet delivered, then those noted.
  for (const record of watch.observer?.takeRecords() ?? []) touchedBy(record, watch.touched);
  flushAll(watch);
  const said = watch.kept.splice(0);
  const focus = describeFocus(doc, isVisible);
  const view = viewOf(doc);
  const scrolled = scrolledAt(doc, at);
  return { ...(focus.ok && focus.element ? { focus: focus.element } : {}), said, ...(view ? { view } : {}), ...(scrolled ? { scrolled } : {}) };
}
