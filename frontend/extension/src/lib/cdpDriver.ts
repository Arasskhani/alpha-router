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
    // The page may not draw over the debugging attach; the rest is lazy.
    await this.refreshViewport();
  }

  async stop(): Promise<void> {
    await this.session.detach();
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
    const shot = await captureViewport(this.session, this.maxSide);
    this.frame = shot.frame;
    this.css = shot.css;
    return shot;
  }

  async zoom(region: Region): Promise<Shot> {
    // The region is given in frame pixels (what the model sees); map it to CSS first.
    if (!this.frame) await this.refreshViewport();
    const topLeft = frameToCss({ x: region.x, y: region.y }, this.frame!);
    const size = frameToCss({ x: region.width, y: region.height }, this.frame!);
    return await captureRegion(this.session, { x: topLeft.x, y: topLeft.y, width: size.x, height: size.y }, this.maxSide);
  }

  async click(
    point: Point,
    options: { button?: MouseButton; clickCount?: number; modifiers?: readonly string[] } = {},
  ): Promise<void> {
    await click(this.session.send.bind(this.session), await this.toCss(point), options);
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

  takeDialog(): DialogInfo | null {
    return this.session.takeDialog();
  }

  async handleDialog(accept: boolean, promptText?: string): Promise<void> {
    await this.session.handleDialog(accept, promptText);
  }
}
