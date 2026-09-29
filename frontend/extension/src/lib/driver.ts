/**
 * Which driver a run uses, chosen per run and failing soft.
 *
 * Full control drives the page through chrome.debugger (the cdp driver). Chrome
 * can refuse the attach - an enterprise policy that sets runtime_blocked_hosts
 * for the extension (Chrome 155+), a screenshot or DLP rule, a DevTools
 * restriction - and full control may simply be off. In every one of those cases
 * the run falls back to the dom path (the existing content-script agent) rather
 * than failing, and the reason is reported so the panel can say which driver is
 * running and why.
 *
 * The dom fallback keeps its current implementation (ref-based actions and
 * captureVisibleTab); this only decides whether to attach the cdp driver. When
 * it returns the cdp driver it is already attached (start() ran); the caller
 * detaches it with stop() when the run ends.
 */

import { CdpSession, type DialogInfo } from "./cdp";
import { CdpDriver, type DialogAnswer } from "./cdpDriver";
import type { Region, Shot } from "./capture";
import type { Point } from "./coords";
import type { MouseButton } from "./input";

export type DriverChoice =
  | { mode: "cdp"; driver: CdpDriver }
  | { mode: "dom"; driver: null; reason: string };

export async function chooseDriver(
  tabId: number,
  options: { fullControl: boolean; maxSide: number },
): Promise<DriverChoice> {
  if (!options.fullControl) return { mode: "dom", driver: null, reason: "full control is off" };
  const driver = new CdpDriver(new CdpSession(tabId), { maxSide: options.maxSide });
  try {
    await driver.start();
    return { mode: "cdp", driver };
  } catch (error) {
    // Chrome refused the attach; leave nothing attached and use the dom path.
    await driver.stop().catch(() => undefined);
    const reason = error instanceof Error ? error.message : String(error);
    return { mode: "dom", driver: null, reason };
  }
}

/**
 * Full control over whichever tab the agent works in.
 *
 * A run starts on the tab next to the panel, but the agent may open a tab or
 * switch to another. A debugger session belongs to one tab, so each tab the
 * agent uses gets its own, attached the first time the agent acts there
 * (use), and the rest of the driver's calls go to that tab's session: its
 * screenshots, its mouse and keyboard, its frame. A session that ended - the
 * tab closed, DevTools opened on it - is attached again once. When Chrome
 * will not attach to a tab, use() says so, and the run works there without
 * full control.
 */
export class TabDrivers {
  private readonly drivers = new Map<number, CdpDriver>();
  /** Tabs Chrome would not attach to, with the page each showed then: another page of the tab is tried again. */
  private readonly refused = new Map<number, string>();
  /** The run is over: an attach still under way is undone as it finishes. */
  private stopped = false;
  private current: CdpDriver | null = null;
  /** The session a dialog last opened in: its answer goes there, whichever tab the agent is on. */
  private dialogIn: CdpDriver | null = null;
  private dialogCb: ((dialog: DialogInfo, answer: DialogAnswer) => Promise<void>) | null = null;
  private readonly maxSide: number;
  private readonly onDetached: (reason: string) => void;

  /**
   * `first`: the tab the run starts on, attached already - or, when Chrome
   * would not attach there (a New Tab page, the Web Store, a page too busy
   * to answer), that tab and the page it showed: the agent gets full control
   * on the first page it reaches that Chrome allows, and does not wait on
   * that page again. Null when the run starts on no tab.
   */
  constructor(
    first: { tabId: number; driver: CdpDriver } | { tabId: number; refusedAt: string } | null,
    options: { maxSide: number; onDetached: (reason: string) => void },
  ) {
    this.maxSide = options.maxSide;
    this.onDetached = options.onDetached;
    if (first && "driver" in first) {
      this.current = first.driver;
      this.adopt(first.tabId, first.driver);
    } else if (first) {
      this.refused.set(first.tabId, first.refusedAt);
    }
  }

  /** The session of the tab the agent works in; there is none before use() first succeeds. */
  private live(): CdpDriver {
    if (!this.current) throw new Error("Full control is not on in this tab.");
    return this.current;
  }

  /** `work` on that session - a rejected promise, never a throw, when there is none. */
  private onLive<T>(work: (driver: CdpDriver) => Promise<T>): Promise<T> {
    try {
      return work(this.live());
    } catch (err) {
      return Promise.reject(err instanceof Error ? err : new Error(String(err)));
    }
  }

  private adopt(tabId: number, driver: CdpDriver): void {
    this.drivers.set(tabId, driver);
    driver.onDetached((reason) => this.onDetached(reason));
    this.bindDialogs(driver);
  }

  private bindDialogs(driver: CdpDriver): void {
    const cb = this.dialogCb;
    driver.onDialog(
      cb
        ? async (dialog, answer) => {
            this.dialogIn = driver;
            await cb(dialog, answer);
          }
        : null,
    );
  }

  /**
   * Work in this tab from now on: its session, attached now if it is not
   * yet (or no longer). False when Chrome will not attach to it.
   */
  async use(tabId: number, url = ""): Promise<boolean> {
    if (this.stopped) return false;
    const known = this.drivers.get(tabId);
    if (known?.attached) {
      this.current = known;
      return true;
    }
    // Refused on this page before: not tried again until the tab shows another (a policy may block one site only).
    // Either way the agent works in this tab now, without a session: nothing goes to the tab it left.
    if (this.refused.get(tabId) === url) {
      this.current = null;
      return false;
    }
    // A session Chrome ended keeps no say in this tab: its dialogs callback goes with it.
    known?.onDialog(null);
    const driver = new CdpDriver(new CdpSession(tabId), { maxSide: this.maxSide });
    try {
      await driver.start();
    } catch {
      await driver.stop().catch(() => undefined);
      this.refused.set(tabId, url);
      this.current = null;
      return false;
    }
    // The run ended while Chrome attached: nothing stays attached after it (the debugging bar, the focus emulation).
    if (this.stopped) {
      await driver.stop().catch(() => undefined);
      return false;
    }
    this.adopt(tabId, driver);
    this.current = driver;
    return true;
  }

  /** Whether this tab is under full control now: its session attached. */
  controls(tabId: number): boolean {
    return !this.stopped && this.drivers.get(tabId)?.attached === true;
  }

  onDialog(cb: ((dialog: DialogInfo, answer: DialogAnswer) => Promise<void>) | null): void {
    this.dialogCb = cb;
    for (const driver of this.drivers.values()) this.bindDialogs(driver);
  }

  async handleDialog(accept: boolean, promptText?: string): Promise<void> {
    await (this.dialogIn ?? this.live()).handleDialog(accept, promptText);
  }

  screenshot(): Promise<Shot> {
    return this.onLive((driver) => driver.screenshot());
  }

  zoom(region: Region): Promise<Shot> {
    return this.onLive((driver) => driver.zoom(region));
  }

  crop(rect: Region, options?: { padding?: number; side?: number }): Promise<Shot> {
    return this.onLive((driver) => driver.crop(rect, options));
  }

  toCss(point: Point): Promise<Point> {
    return this.onLive((driver) => driver.toCss(point));
  }

  click(point: Point, options?: { button?: MouseButton; clickCount?: number; modifiers?: readonly string[] }): Promise<void> {
    return this.onLive((driver) => driver.click(point, options));
  }

  clickAt(css: Point, options?: { button?: MouseButton; clickCount?: number; modifiers?: readonly string[] }): Promise<void> {
    return this.onLive((driver) => driver.clickAt(css, options));
  }

  hover(point: Point, modifiers?: readonly string[]): Promise<void> {
    return this.onLive((driver) => driver.hover(point, modifiers));
  }

  scroll(point: Point, delta: { x?: number; y?: number }): Promise<void> {
    return this.onLive((driver) => driver.scroll(point, delta));
  }

  drag(from: Point, to: Point): Promise<{ intercepted: boolean }> {
    return this.onLive((driver) => driver.drag(from, to));
  }

  type(text: string): Promise<void> {
    return this.onLive((driver) => driver.type(text));
  }

  key(spec: string, modifiers?: readonly string[]): Promise<boolean> {
    return this.onLive((driver) => driver.key(spec, modifiers));
  }

  /** Detach from every tab the run attached to, and attach to none from now on. */
  async stop(): Promise<void> {
    this.stopped = true;
    await Promise.all([...this.drivers.values()].map((driver) => driver.stop().catch(() => undefined)));
  }
}

