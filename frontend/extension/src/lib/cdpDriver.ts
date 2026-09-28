/**
 * The CDP driver: the agent's input and screenshots under full control.
 *
 * It owns a CdpSession and turns the tools' high-level asks - click at this
 * frame point, type this text, take a screenshot - into the trusted CDP gestures
 * (input.ts, keys.ts) and captures (capture.ts). The model works in frame
 * coordinates (the screenshot's pixels); the driver keeps the frame from the
 * last screenshot and maps a frame point to a CSS pixel (coords.ts) before it
 * sends any pointer event, refreshing the frame from the viewport when it has
 * none yet. It never reads or judges the page - that is the DOM layer and the
 * rules - it only carries out an action once allowed.
 */

import { CdpSession, type DialogInfo } from "./cdp";
import { type Frame, frameFor, frameToCss, clampToViewport, type Point, type Size } from "./coords";
import { captureRegion, captureViewport, viewportSize, type Region, type Shot } from "./capture";
import { click, drag, hover, type MouseButton, scrollBy } from "./input";
import { insertText, pressKey } from "./keys";

export type DriverMode = "cdp" | "dom";

/** The reviewer's crop: this much of the page around the target, in CSS pixels, and at most this big. */
const CROP_PADDING = 24;
const CROP_SIDE = 640;

/** Answering one dialog: accept (with a prompt's text) or dismiss it. */
export type DialogAnswer = (accept: boolean, promptText?: string) => Promise<void>;

export class CdpDriver {
  readonly mode: DriverMode = "cdp";
  private readonly session: CdpSession;
  private readonly maxSide: number;
  private frame: Frame | null = null;
  private css: Size | null = null;

  constructor(session: CdpSession, options: { maxSide: number }) {
    this.session = session;
    this.maxSide = options.maxSide;
  }

  onDetached(cb: (reason: string) => void): void {
    this.session.onDetached(cb);
  }

  async start(): Promise<void> {
    await this.session.attach();
    // The Page domain's events: without them Chrome never says a dialog opened, and the page just waits.
    await this.session.send("Page.enable");
    // The page keeps its focus while the person answers a card in the side panel: a blur there closes
    // the page's menus and suggestion lists (Gmail's recipients), and moves what the rules just judged.
    await this.session.send("Emulation.setFocusEmulationEnabled", { enabled: true }).catch(() => undefined);
    // The page may not draw over the debugging attach; the rest is lazy.
    await this.refreshViewport();
  }

  async stop(): Promise<void> {
    await this.session.detach();
  }

  /** Whether the session is still attached (Chrome ends it when the tab closes, or DevTools takes it). */
  get attached(): boolean {
    return this.session.isAttached;
  }

  /**
   * The tab in front, before a capture: Chrome draws no frames for a tab in
   * the background, and a screenshot of one waits for a frame that never
   * comes. Best-effort: an old browser without the command still captures.
   */
  private async front(): Promise<void> {
    await this.session.send("Page.bringToFront").catch(() => undefined);
  }

  private async refreshViewport(): Promise<Size> {
    this.css = await viewportSize(this.session);
    this.frame = frameFor(this.css, this.maxSide);
    return this.css;
  }

  /** A point in the last screenshot's pixels as the CSS pixel it names, clamped to the viewport. */
  async toCss(point: Point): Promise<Point> {
    if (!this.frame || !this.css) await this.refreshViewport();
    const css = frameToCss(point, this.frame!);
    return clampToViewport(css, this.css!);
  }

  async screenshot(): Promise<Shot> {
    await this.front();
    const shot = await captureViewport(this.session, this.maxSide);
    this.frame = shot.frame;
    this.css = shot.css;
    return shot;
  }

  /**
   * The page around a target, for the reviewer: the target's box in CSS
   * pixels (as the page described it), with some of what surrounds it, at
   * most `side` pixels on its longest side and never magnified more than
   * twice - a small icon is not blown up into a page-sized picture.
   */
  async crop(rect: Region, options: { padding?: number; side?: number } = {}): Promise<Shot> {
    if (!this.css) await this.refreshViewport();
    const css = this.css!;
    const padding = options.padding ?? CROP_PADDING;
    const x0 = Math.max(0, Math.min(css.width, rect.x - padding));
    const y0 = Math.max(0, Math.min(css.height, rect.y - padding));
    const x1 = Math.max(x0 + 1, Math.min(css.width, rect.x + rect.width + padding));
    const y1 = Math.max(y0 + 1, Math.min(css.height, rect.y + rect.height + padding));
    const region = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
    const side = Math.min(options.side ?? CROP_SIDE, 2 * Math.max(region.width, region.height));
    await this.front();
    return await captureRegion(this.session, region, side);
  }

  async zoom(region: Region): Promise<Shot> {
    // The region is given in frame pixels (what the model sees); map it to CSS first.
    if (!this.frame) await this.refreshViewport();
    const topLeft = frameToCss({ x: region.x, y: region.y }, this.frame!);
    const size = frameToCss({ x: region.width, y: region.height }, this.frame!);
    await this.front();
    return await captureRegion(this.session, { x: topLeft.x, y: topLeft.y, width: size.x, height: size.y }, this.maxSide);
  }

  async click(
    point: Point,
    options: { button?: MouseButton; clickCount?: number; modifiers?: readonly string[] } = {},
  ): Promise<void> {
    await click(this.session.send.bind(this.session), await this.toCss(point), options);
  }

  /** A click at a point in CSS pixels - an element's centre, as the page gave it - rather than in the screenshot's. */
  async clickAt(css: Point, options: { button?: MouseButton; clickCount?: number; modifiers?: readonly string[] } = {}): Promise<void> {
    await click(this.session.send.bind(this.session), css, options);
  }

  async hover(point: Point, modifiers: readonly string[] = []): Promise<void> {
    await hover(this.session.send.bind(this.session), await this.toCss(point), modifiers);
  }

  async scroll(point: Point, delta: { x?: number; y?: number }): Promise<void> {
    await scrollBy(this.session.send.bind(this.session), await this.toCss(point), delta);
  }

  async drag(from: Point, to: Point): Promise<{ intercepted: boolean }> {
    return await drag(
      this.session.send.bind(this.session),
      await this.toCss(from),
      await this.toCss(to),
      () => this.session.takeDragData(),
    );
  }

  async type(text: string): Promise<void> {
    await insertText(this.session.send.bind(this.session), text);
  }

  async key(spec: string, modifiers: readonly string[] = []): Promise<boolean> {
    return await pressKey(this.session.send.bind(this.session), spec, modifiers);
  }

  /**
   * Who answers the page's JavaScript dialogs: called as one opens, while the
   * input that opened it waits for the answer (null: nobody), with the way to
   * answer this very dialog - in this tab, whichever the agent is on by then.
   */
  onDialog(cb: ((dialog: DialogInfo, answer: DialogAnswer) => Promise<void>) | null): void {
    this.session.onDialog(cb ? (dialog) => void cb(dialog, (accept, promptText) => this.handleDialog(accept, promptText)).catch(() => undefined) : null);
  }

  async handleDialog(accept: boolean, promptText?: string): Promise<void> {
    await this.session.handleDialog(accept, promptText);
  }
}
