/**
 * Between the screenshot the model sees and the CSS pixels CDP input wants.
 *
 * A screenshot is the visual viewport, scaled down so its longest side is at
 * most `maxSide`, so a big or high-DPI screen still fits a sane image. The
 * model reads that image and answers in its pixels ("click at 420, 300"). CDP
 * `Input.*` events, though, take CSS pixels in the viewport's own frame. So a
 * point the model gives is divided by the scale to become a CSS pixel, and a
 * CSS rect (an element's `getBoundingClientRect`) is multiplied by the scale to
 * become the frame coordinates the model would name.
 *
 * The scale is derived from the viewport's CSS size, which `Page.getLayoutMetrics`
 * reports as `cssVisualViewport` (falling back to `cssLayoutViewport`). Device
 * pixel ratio and page zoom are already folded into that CSS size, so nothing
 * here multiplies by them again.
 */

export type Point = { x: number; y: number };
export type Size = { width: number; height: number };
/** A screenshot frame: its pixel size, and the scale from CSS pixels to it. */
export type Frame = { width: number; height: number; scale: number };

/** The longest side a screenshot may have, unless an admin narrows it (see the plan). */
export const DEFAULT_MAX_SIDE = 1280;
const MIN_MAX_SIDE = 400;
const MAX_MAX_SIDE = 4096;

export function clampMaxSide(value: number | undefined): number {
  if (!Number.isFinite(value)) return DEFAULT_MAX_SIDE;
  return Math.min(MAX_MAX_SIDE, Math.max(MIN_MAX_SIDE, Math.round(value as number)));
}

/**
 * The frame a viewport of `css` size produces at `maxSide`.
 *
 * Never scales up: a viewport already smaller than `maxSide` is shown at its own
 * size (scale 1), so coordinates stay exact.
 */
export function frameFor(css: Size, maxSide: number = DEFAULT_MAX_SIDE): Frame {
  const longest = Math.max(css.width, css.height);
  const scale = longest > maxSide && longest > 0 ? maxSide / longest : 1;
  return { width: Math.max(1, Math.round(css.width * scale)), height: Math.max(1, Math.round(css.height * scale)), scale };
}

/** A point the model gave, in frame pixels, as a CSS pixel in the viewport. */
export function frameToCss(point: Point, frame: Frame): Point {
  return { x: point.x / frame.scale, y: point.y / frame.scale };
}

/** A CSS point (an element centre, say) as the frame pixel the model would name. */
export function cssToFrame(point: Point, frame: Frame): Point {
  return { x: point.x * frame.scale, y: point.y * frame.scale };
}

/** Keep a CSS point inside the viewport, so an off-by-one never lands outside it. */
export function clampToViewport(point: Point, css: Size): Point {
  return {
    x: Math.min(Math.max(point.x, 0), Math.max(0, css.width - 1)),
    y: Math.min(Math.max(point.y, 0), Math.max(0, css.height - 1)),
  };
}

/** A viewport as `Page.getLayoutMetrics` reports it: its size is `clientWidth`/`clientHeight`. */
type ViewportMetrics = { clientWidth?: unknown; clientHeight?: unknown; width?: unknown; height?: unknown };

function positive(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

/**
 * Device pixels per CSS pixel, from a Page.getLayoutMetrics reply: the
 * display scale (a Windows laptop at 150 % is 1.5) times the page zoom.
 * `Page.captureScreenshot` answers in device pixels, so a capture scaled for
 * the frame is divided by this. The deprecated viewports without the `css`
 * prefix are in device pixels; their ratio to the CSS ones is the scale. 1
 * when the reply cannot tell.
 */
export function deviceScaleFromMetrics(metrics: unknown): number {
  const m = metrics as {
    visualViewport?: ViewportMetrics;
    cssVisualViewport?: ViewportMetrics;
    layoutViewport?: ViewportMetrics;
    cssLayoutViewport?: ViewportMetrics;
  } | null;
  for (const [device, css] of [
    [m?.visualViewport, m?.cssVisualViewport],
    [m?.layoutViewport, m?.cssLayoutViewport],
  ] as const) {
    const ratio = positive(device?.clientWidth) && positive(css?.clientWidth) ? device.clientWidth / css.clientWidth : NaN;
    if (Number.isFinite(ratio) && ratio >= 0.25 && ratio <= 8) return Math.round(ratio * 1000) / 1000;
  }
  return 1;
}

/**
 * The CSS viewport size from a Page.getLayoutMetrics reply, or null if it has none.
 *
 * Chromium names the size `clientWidth`/`clientHeight` (the viewport without
 * its scroll bars); `width`/`height` is read too, in case a browser ever sends
 * that instead. The visual viewport comes first, the layout viewport after.
 */
export function cssViewportFromMetrics(metrics: unknown): Size | null {
  const m = metrics as { cssVisualViewport?: ViewportMetrics; cssLayoutViewport?: ViewportMetrics } | null;
  for (const vp of [m?.cssVisualViewport, m?.cssLayoutViewport]) {
    const width = vp?.clientWidth ?? vp?.width;
    const height = vp?.clientHeight ?? vp?.height;
    if (positive(width) && positive(height)) return { width, height };
  }
  return null;
}
